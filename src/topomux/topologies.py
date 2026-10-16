from __future__ import annotations

import json
import numbers
from pathlib import Path
from typing import IO

import networkx as nx


def ring(n: int) -> nx.Graph:
    """Ring topology: edge (r, 1) <-> ((r+1) % n, 0)."""
    g = nx.Graph()
    for r in range(n):
        next_r = (r + 1) % n
        g.add_edge((r, 1), (next_r, 0))
    return g


def reverse_ring(n: int) -> nx.Graph:
    """Reverse ring: edge (r, 0) <-> ((r+1) % n, 1)."""
    g = nx.Graph()
    for r in range(n):
        next_r = (r + 1) % n
        g.add_edge((r, 0), (next_r, 1))
    return g


def loopback(n: int, links_per_rank: int = 2) -> nx.Graph:
    """Loopback topology: every link loops back to itself."""
    g = nx.Graph()
    for r in range(n):
        for link in range(links_per_rank):
            g.add_edge((r, link), (r, link))
    return g


def pair(n: int) -> nx.Graph:
    """Pair topology: cross-connect link 0 with link 1 within each rank."""
    g = nx.Graph()
    for r in range(n):
        g.add_edge((r, 0), (r, 1))
    return g


def from_edge_list(edges: list[tuple]) -> nx.Graph:
    """Build topology from explicit ((rank, link), (rank, link)) edge tuples."""
    g = nx.Graph()
    for src, dst in edges:
        g.add_edge(tuple(src), tuple(dst))
    validate(g)
    return g


def from_file(path: str | Path) -> nx.Graph:
    """Parse a .topo file.

    Supports edge lines (``0.1 - 1.0``) and shorthand commands
    (``ring 4``, ``reverse-ring 4``, ``loopback 3 4``, ``pair 3``).
    """
    g = nx.Graph()
    path = Path(path)
    for raw_line in path.read_text().splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue

        if "-" in line and "." in line:
            _parse_edge_line(g, line)
        else:
            _parse_command_line(g, line)

    validate(g)
    return g


def from_json(source: str | Path | IO[str]) -> nx.Graph:
    """Load a node-link JSON graph, as written by ``to_json`` or
    ``json.dump(nx.node_link_data(g, edges="edges"), f)``.

    ``source`` is a path or an open text file. Node ids are
    ``[rank, link]`` lists; they become ``(rank, link)`` tuples."""
    if isinstance(source, (str, Path)):
        text = Path(source).read_text()
    else:
        text = source.read()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON: {e}") from None
    if not isinstance(data, dict):
        raise ValueError("node-link JSON must be an object")
    if "links" in data and "edges" not in data:
        raise ValueError(
            'node-link JSON uses the old "links" key; write it with '
            'nx.node_link_data(g, edges="edges") or topomux.to_json(g)'
        )
    if data.get("directed"):
        raise ValueError("directed graphs are not supported")
    try:
        g = nx.node_link_graph(data, edges="edges")
    except (KeyError, TypeError, nx.NetworkXError) as e:
        raise ValueError(f"invalid node-link JSON: {e!r}") from None
    validate(g)
    return g


def to_json(g: nx.Graph) -> str:
    """Serialize a topology as node-link JSON, readable by ``from_json``."""
    validate(g)
    return json.dumps(nx.node_link_data(g, edges="edges"))


def _parse_edge_line(g: nx.Graph, line: str) -> None:
    left, right = line.split("-", 1)
    src = _parse_endpoint(left.strip())
    dst = _parse_endpoint(right.strip())
    g.add_edge(src, dst)


def _parse_endpoint(s: str) -> tuple[int, int]:
    parts = s.split(".")
    if len(parts) != 2:
        raise ValueError(f"Invalid endpoint '{s}', expected rank.link")
    return int(parts[0]), int(parts[1])


_COMMANDS = {}


def _register(name: str):
    def decorator(fn):
        _COMMANDS[name] = fn
        return fn
    return decorator


@_register("ring")
def _cmd_ring(args: list[str]) -> nx.Graph:
    return ring(int(args[0]))


@_register("reverse-ring")
def _cmd_reverse_ring(args: list[str]) -> nx.Graph:
    return reverse_ring(int(args[0]))


@_register("loopback")
def _cmd_loopback(args: list[str]) -> nx.Graph:
    n = int(args[0])
    lpr = int(args[1]) if len(args) >= 2 else 2
    return loopback(n, links_per_rank=lpr)


@_register("pair")
def _cmd_pair(args: list[str]) -> nx.Graph:
    return pair(int(args[0]))


def _parse_command_line(g: nx.Graph, line: str) -> None:
    parts = line.split()
    cmd_name = parts[0].lower()
    if cmd_name not in _COMMANDS:
        raise ValueError(f"Unknown command '{cmd_name}' in topology file")
    sub_graph = _COMMANDS[cmd_name](parts[1:])
    g.update(sub_graph)


def ranks(g: nx.Graph) -> list[int]:
    """Return sorted list of unique rank IDs in the graph."""
    return sorted({r for r, _link in g.nodes})


def links(g: nx.Graph, rank: int) -> list[int]:
    """Return sorted list of link IDs used by the given rank."""
    return sorted({link for r, link in g.nodes if r == rank})


def _is_int(x) -> bool:
    """Any integer type (int, numpy.int64, ...) except bool."""
    return isinstance(x, numbers.Integral) and not isinstance(x, bool)


def validate(g: nx.Graph) -> None:
    """Raise ValueError if any node is not a (rank, link) tuple of
    non-negative integers, or if any node is part of more than one edge
    (a self-loop counts as one)."""
    for node in g.nodes:
        if (
            not isinstance(node, tuple)
            or len(node) != 2
            or not all(_is_int(x) for x in node)
        ):
            raise ValueError(
                f"Node {node!r} is not a (rank: int, link: int) tuple"
            )
        if node[0] < 0 or node[1] < 0:
            raise ValueError(
                f"Node {node!r} has a negative rank or link"
            )

    incident: dict[tuple[int, int], list[tuple]] = {}
    for u, v in g.edges():
        incident.setdefault(u, []).append((u, v))
        if v != u:
            incident.setdefault(v, []).append((u, v))
    for node, edges in incident.items():
        if len(edges) > 1:
            raise ValueError(
                f"Node {node!r} is part of {len(edges)} edges {edges!r}, "
                f"expected at most one"
            )

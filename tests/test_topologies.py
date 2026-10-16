from pathlib import Path

import networkx as nx
import numpy as np
import pytest

import topomux

TOPO_DIR = Path(__file__).resolve().parent.parent / "topologies"


def edge_set(g: nx.Graph) -> set[frozenset]:
    return {frozenset((u, v)) for u, v in g.edges}


def test_ring():
    assert edge_set(topomux.ring(3)) == edge_set(topomux.from_edge_list([
        ((0, 1), (1, 0)),
        ((1, 1), (2, 0)),
        ((2, 1), (0, 0)),
    ]))


def test_ring_single_rank_connects_own_links():
    assert edge_set(topomux.ring(1)) == {frozenset({(0, 1), (0, 0)})}


def test_reverse_ring():
    assert edge_set(topomux.reverse_ring(3)) == edge_set(topomux.from_edge_list([
        ((0, 0), (1, 1)),
        ((1, 0), (2, 1)),
        ((2, 0), (0, 1)),
    ]))


def test_loopback():
    g = topomux.loopback(2, links_per_rank=3)
    assert edge_set(g) == {
        frozenset({(r, link)}) for r in range(2) for link in range(3)
    }


def test_pair():
    assert edge_set(topomux.pair(2)) == {
        frozenset({(0, 0), (0, 1)}),
        frozenset({(1, 0), (1, 1)}),
    }


def test_ranks_and_links():
    g = topomux.from_edge_list([((0, 0), (2, 3)), ((2, 1), (2, 1))])
    assert topomux.ranks(g) == [0, 2]
    assert topomux.links(g, 2) == [1, 3]


@pytest.mark.parametrize(
    "path", sorted(TOPO_DIR.glob("*.topo")), ids=lambda p: p.name
)
def test_shipped_topo_files_are_valid(path):
    g = topomux.from_file(path)
    assert g.number_of_edges() > 0


def test_from_file_edges_commands_and_comments(tmp_path):
    f = tmp_path / "t.topo"
    f.write_text(
        "# comment\n"
        "\n"
        "pair 1\n"
        "1.0 - 2.1  # trailing comment\n"
    )
    assert edge_set(topomux.from_file(f)) == {
        frozenset({(0, 0), (0, 1)}),
        frozenset({(1, 0), (2, 1)}),
    }


def test_from_file_matches_shorthand():
    g = topomux.from_file(TOPO_DIR / "xilinx_ring.topo")
    assert edge_set(g) == edge_set(topomux.ring(3))


def test_from_file_unknown_command(tmp_path):
    f = tmp_path / "t.topo"
    f.write_text("star 4\n")
    with pytest.raises(ValueError, match="Unknown command"):
        topomux.from_file(f)


def test_from_file_bad_endpoint(tmp_path):
    f = tmp_path / "t.topo"
    f.write_text("0.0.0 - 1.1\n")
    with pytest.raises(ValueError, match="Invalid endpoint"):
        topomux.from_file(f)


def test_from_file_overlapping_commands_rejected(tmp_path):
    f = tmp_path / "t.topo"
    f.write_text("ring 2\nloopback 2\n")
    with pytest.raises(ValueError, match="at most one"):
        topomux.from_file(f)


@pytest.mark.parametrize(
    "node", [0, (0,), (0, 0, 0), ("0", 0), (0, 1.0), (True, 0), (0, False)],
)
def test_validate_rejects_malformed_nodes(node):
    g = nx.Graph()
    g.add_node(node)
    with pytest.raises(ValueError, match="not a"):
        topomux.validate(g)


def test_validate_accepts_self_loop_and_isolated_node():
    g = nx.Graph()
    g.add_edge((0, 0), (0, 0))
    g.add_node((1, 0))
    topomux.validate(g)


def test_validate_rejects_link_with_two_peers():
    g = nx.Graph()
    g.add_edge((0, 0), (1, 0))
    g.add_edge((0, 0), (2, 0))
    with pytest.raises(ValueError, match=r"Node \(0, 0\) is part of 2 edges"):
        topomux.validate(g)


def test_validate_rejects_self_loop_plus_peer():
    g = nx.Graph()
    g.add_edge((0, 0), (0, 0))
    g.add_edge((0, 0), (1, 0))
    with pytest.raises(ValueError, match="at most one"):
        topomux.validate(g)


def test_validate_rejects_parallel_multigraph_edges():
    g = nx.MultiGraph()
    g.add_edge((0, 0), (1, 0))
    g.add_edge((0, 0), (1, 0))
    with pytest.raises(ValueError, match="at most one"):
        topomux.validate(g)


def test_from_edge_list_validates():
    with pytest.raises(ValueError, match="at most one"):
        topomux.from_edge_list([((0, 0), (1, 0)), ((0, 0), (2, 0))])


@pytest.mark.parametrize("node", [(-1, 0), (0, -1)])
def test_validate_rejects_negative(node):
    g = nx.Graph()
    g.add_node(node)
    with pytest.raises(ValueError, match="negative"):
        topomux.validate(g)


def test_validate_accepts_numpy_ints():
    g = nx.Graph()
    g.add_edge((np.int64(0), np.int64(1)), (np.int32(1), 0))
    topomux.validate(g)

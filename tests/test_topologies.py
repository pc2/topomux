import io
import json
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


@pytest.mark.parametrize("g", [
    topomux.ring(3),
    topomux.reverse_ring(2),
    topomux.loopback(2, links_per_rank=4),
    topomux.pair(3),
], ids=["ring", "reverse-ring", "loopback", "pair"])
def test_json_round_trip(tmp_path, g):
    f = tmp_path / "g.json"
    f.write_text(topomux.to_json(g))
    h = topomux.from_json(f)
    assert set(h.nodes) == set(g.nodes)
    assert edge_set(h) == edge_set(g)
    assert all(isinstance(n, tuple) for n in h.nodes)


def test_json_keeps_nodes_without_edges():
    g = topomux.loopback(1, links_per_rank=1)
    g.add_node((1, 0))
    h = topomux.from_json(io.StringIO(topomux.to_json(g)))
    assert set(h.nodes) == {(0, 0), (1, 0)}


def test_json_from_plain_networkx(tmp_path):
    g = nx.Graph()
    g.add_edge((0, 0), (1, 1))
    f = tmp_path / "g.json"
    f.write_text(json.dumps(nx.node_link_data(g, edges="edges")))
    assert edge_set(topomux.from_json(str(f))) == {frozenset({(0, 0), (1, 1)})}


@pytest.mark.parametrize("text, match", [
    ("{", "invalid JSON"),
    ("[1]", "must be an object"),
    ('{"nodes": [{"id": [0, 0]}], "links": []}', 'old "links" key'),
    ('{"directed": true, "nodes": [], "edges": []}', "directed"),
    ('{"nodes": [{"id": [0, 0]}]}', "invalid node-link JSON"),
    ('{"nodes": [{"id": "a"}], "edges": []}', "not a"),
    ('{"nodes": [{"id": [0, 0]}, {"id": [1, 0]}, {"id": [2, 0]}], "edges": ['
     '{"source": [0, 0], "target": [1, 0]},'
     '{"source": [0, 0], "target": [2, 0]}]}', "at most one"),
])
def test_from_json_rejects(text, match):
    with pytest.raises(ValueError, match=match):
        topomux.from_json(io.StringIO(text))


def test_to_json_validates():
    g = nx.Graph()
    g.add_node(("0", 0))
    with pytest.raises(ValueError):
        topomux.to_json(g)


def test_switch():
    assert edge_set(topomux.switch(2)) == {
        frozenset({(0, 0), ("eth", 0)}),
        frozenset({(1, 0), ("eth", 1)}),
    }


def test_direct():
    assert edge_set(topomux.direct(4)) == {
        frozenset({(0, 0), (1, 0)}),
        frozenset({(2, 0), (3, 0)}),
    }


def test_direct_pairs_every_link_with_the_same_link_of_the_partner():
    assert edge_set(topomux.direct(2, links_per_rank=2)) == {
        frozenset({(0, 0), (1, 0)}),
        frozenset({(0, 1), (1, 1)}),
    }


def test_switch_gives_every_link_its_own_port():
    assert edge_set(topomux.switch(2, links_per_rank=2)) == {
        frozenset({(0, 0), ("eth", 0)}),
        frozenset({(0, 1), ("eth", 1)}),
        frozenset({(1, 0), ("eth", 2)}),
        frozenset({(1, 1), ("eth", 3)}),
    }


def test_switch_and_direct_commands_take_a_link_count(tmp_path):
    path = tmp_path / "two_links.topo"
    path.write_text("switch 2 2\n")
    assert edge_set(topomux.from_file(path)) == edge_set(topomux.switch(2, links_per_rank=2))
    path.write_text("direct 2 2\n")
    assert edge_set(topomux.from_file(path)) == edge_set(topomux.direct(2, links_per_rank=2))


def test_direct_rejects_odd_rank_count():
    with pytest.raises(ValueError, match="even"):
        topomux.direct(3)


def test_from_file_device_endpoint(tmp_path):
    f = tmp_path / "t.topo"
    f.write_text("0.1 - eth.3\ndirect 2 1\n")
    assert edge_set(topomux.from_file(f)) == {
        frozenset({(0, 1), ("eth", 3)}),
        frozenset({(0, 0), (1, 0)}),
    }


def test_from_file_unknown_device(tmp_path):
    f = tmp_path / "t.topo"
    f.write_text("0.0 - wifi.0\n")
    with pytest.raises(ValueError, match="Invalid endpoint"):
        topomux.from_file(f)


def test_validate_rejects_unknown_device():
    g = nx.Graph()
    g.add_node(("wifi", 0))
    with pytest.raises(ValueError, match="not a"):
        topomux.validate(g)


def test_validate_rejects_device_to_device_edge():
    g = nx.Graph()
    g.add_edge(("eth", 0), ("eth", 1))
    with pytest.raises(ValueError, match="two devices"):
        topomux.validate(g)


def test_ranks_lists_devices_last():
    assert topomux.ranks(topomux.switch(2)) == [0, 1, "eth"]
    assert topomux.links(topomux.switch(2), "eth") == [0, 1]


def test_json_round_trip_with_device():
    g = topomux.switch(2)
    h = topomux.from_json(io.StringIO(topomux.to_json(g)))
    assert edge_set(h) == edge_set(g)

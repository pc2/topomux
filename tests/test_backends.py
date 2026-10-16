import os
import stat
import subprocess
from pathlib import Path

import networkx as nx
import pytest

import topomux


def test_node_mapping():
    m = topomux.NodeMapping(fpgas_per_node=3)
    assert [m.format(r) for r in (0, 2, 3, 31)] == [
        "n00:acl0", "n00:acl2", "n01:acl0", "n10:acl1",
    ]


def test_hardware_ring():
    hw = topomux.HardwareBackend(topomux.NodeMapping(fpgas_per_node=3))
    assert hw.emit(topomux.ring(3)) == [
        "--fpgalink=n00:acl0:ch1-n00:acl1:ch0",
        "--fpgalink=n00:acl1:ch1-n00:acl2:ch0",
        "--fpgalink=n00:acl2:ch1-n00:acl0:ch0",
    ]


def test_hardware_loopback():
    hw = topomux.HardwareBackend(topomux.NodeMapping(fpgas_per_node=2))
    assert hw.emit(topomux.loopback(1, links_per_rank=2)) == [
        "--fpgalink=n00:acl0:ch0-n00:acl0:ch0",
        "--fpgalink=n00:acl0:ch1-n00:acl0:ch1",
    ]


def test_hardware_gui_url():
    hw = topomux.HardwareBackend()
    assert hw.emit_gui_url(topomux.pair(1)) == (
        "https://pc2.github.io/fpgalink-gui/index.html"
        "?import=--fpgalink%3Dn00%3Aacl0%3Ach0-n00%3Aacl0%3Ach1"
    )


def test_hardware_validates():
    g = nx.Graph()
    g.add_edge((0, 0), (1, 0))
    g.add_edge((0, 0), (2, 0))
    with pytest.raises(ValueError):
        topomux.HardwareBackend().emit(g)


def test_emulation_loopback_relative():
    emu = topomux.EmulationBackend(base_dir="pipes")
    assert emu.emit(topomux.loopback(1, links_per_rank=1)) == [
        "mkdir -p pipes/rank0",
        "mkfifo pipes/rank0/link_i0_tx",
        "ln -s link_i0_tx pipes/rank0/link_i0_rx",
    ]


def test_emulation_pair_absolute():
    emu = topomux.EmulationBackend(base_dir="/tmp/pipes")
    assert emu.emit(topomux.pair(1)) == [
        "mkdir -p /tmp/pipes/rank0",
        "mkfifo /tmp/pipes/rank0/link_i0_tx",
        "mkfifo /tmp/pipes/rank0/link_i1_tx",
        "ln -s /tmp/pipes/rank0/link_i1_tx /tmp/pipes/rank0/link_i0_rx",
        "ln -s /tmp/pipes/rank0/link_i0_tx /tmp/pipes/rank0/link_i1_rx",
    ]


def test_emulation_bsp_overlay():
    emu = topomux.EmulationBackend(
        base_dir="p", bsp=topomux.BittwareS10BSP(),
    )
    actions = emu.emit(topomux.ring(1))
    assert actions[-4:] == [
        "ln -s link_i0_tx p/rank0/1",
        "ln -s link_i0_rx p/rank0/0",
        "ln -s link_i1_tx p/rank0/3",
        "ln -s link_i1_rx p/rank0/2",
    ]


def test_emulation_validates():
    g = nx.Graph()
    g.add_edge((0, 0), (1, 0))
    g.add_edge((0, 0), (2, 0))
    with pytest.raises(ValueError):
        topomux.EmulationBackend(base_dir="p").emit(g)


def _apply(actions: list[str], cwd: Path) -> None:
    subprocess.run(
        ["bash", "-e"], input="\n".join(actions), text=True,
        cwd=cwd, check=True,
    )


def _assert_wired(base: Path, g: nx.Graph) -> None:
    """Every rx resolves to its peer's tx FIFO (its own for a loopback)."""
    for a, b in g.edges:
        for (r, link), (peer_r, peer_link) in ((a, b), (b, a)):
            rx = base / f"rank{r}" / f"link_i{link}_rx"
            peer_tx = base / f"rank{peer_r}" / f"link_i{peer_link}_tx"
            assert rx.is_symlink()
            assert rx.resolve() == peer_tx.resolve()
            assert stat.S_ISFIFO(os.stat(rx).st_mode)


@pytest.mark.parametrize("graph", [
    topomux.ring(3),
    topomux.reverse_ring(2),
    topomux.loopback(2, links_per_rank=2),
    topomux.pair(2),
], ids=["ring", "reverse-ring", "loopback", "pair"])
@pytest.mark.parametrize("absolute", [True, False], ids=["abs", "rel"])
def test_emulation_applies_cleanly(tmp_path, graph, absolute):
    base = tmp_path / "pipes" if absolute else Path("pipes")
    emu = topomux.EmulationBackend(
        base_dir=base, bsp=topomux.BittwareS10BSP(),
    )
    _apply(emu.emit(graph), cwd=tmp_path)
    _assert_wired(tmp_path / "pipes", graph)

    bsp = topomux.BittwareS10BSP()
    for r in topomux.ranks(graph):
        for link in topomux.links(graph, r):
            rank_dir = tmp_path / "pipes" / f"rank{r}"
            assert (rank_dir / str(bsp.output_id(link))).resolve() == (
                rank_dir / f"link_i{link}_tx").resolve()
            assert (rank_dir / str(bsp.input_id(link))).resolve() == (
                rank_dir / f"link_i{link}_rx").resolve()

from pathlib import Path

import pytest

from topomux.cli import main

TOPO_DIR = Path(__file__).resolve().parent.parent / "topologies"


def run(capsys, *argv: str) -> str:
    assert main(list(argv)) == 0
    return capsys.readouterr().out


def test_hardware_named_topology(capsys):
    out = run(capsys, "ring", "2", "-b", "hardware", "--fpgas-per-node", "2")
    assert out == (
        "--fpgalink=n00:acl0:ch1-n00:acl1:ch0 "
        "--fpgalink=n00:acl1:ch1-n00:acl0:ch0\n"
    )


def test_hardware_loopback_links_per_rank(capsys):
    out = run(capsys, "loopback", "1", "--links-per-rank", "1", "-b", "hardware")
    assert out == "--fpgalink=n00:acl0:ch0-n00:acl0:ch0\n"


def test_hardware_gui_url(capsys):
    out = run(capsys, "pair", "1", "-b", "hardware", "--gui-url")
    assert out.startswith("https://pc2.github.io/fpgalink-gui/index.html?import=")


# The exact arguments the hardware CI jobs pass to changeFPGAlinks{,Xilinx}.
@pytest.mark.parametrize("topo, fpgas_per_node, expected", [
    ("xilinx_loopback.topo", 3, 6),
    ("xilinx_pair.topo", 3, 3),
    ("xilinx_ring.topo", 3, 3),
    ("bittware_loopback.topo", 2, 8),
    ("bittware_pair.topo", 2, 4),
    ("bittware_adjacent.topo", 2, 4),
    ("bittware_different.topo", 2, 4),
])
def test_ci_invocations(capsys, topo, fpgas_per_node, expected):
    out = run(
        capsys, "-f", str(TOPO_DIR / topo), "-b", "hardware",
        "--fpgas-per-node", str(fpgas_per_node),
    )
    args = out.split()
    assert len(args) == expected
    assert all(a.startswith("--fpgalink=") for a in args)


def test_emulation_with_bsp(capsys):
    out = run(
        capsys, "loopback", "1", "--links-per-rank", "1",
        "-b", "emulation", "--base-dir", "p", "--bsp", "bittware_s10",
    )
    assert out.splitlines() == [
        "mkdir -p p/rank0",
        "mkfifo p/rank0/link_i0_tx",
        "ln -s link_i0_tx p/rank0/link_i0_rx",
        "ln -s link_i0_tx p/rank0/1",
        "ln -s link_i0_rx p/rank0/0",
    ]


def test_missing_num_ranks(capsys):
    with pytest.raises(SystemExit):
        main(["ring", "-b", "hardware"])
    assert "num_ranks is required" in capsys.readouterr().err


def test_backend_required():
    with pytest.raises(SystemExit):
        main(["ring", "2"])

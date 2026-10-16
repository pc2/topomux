import contextlib
import io
import re
import subprocess
import sys
from pathlib import Path

import pytest

import topomux
from topomux.cli import build_parser, main

TOPO_DIR = Path(__file__).resolve().parent.parent / "topologies"


@contextlib.contextmanager
def raises_usage_error(capsys, match: str):
    """Expect main() to exit with code 2 and a one-line error on stderr."""
    with pytest.raises(SystemExit) as exc:
        yield
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert re.search(r"topomux: error: .*" + match, err), err
    assert "Traceback" not in err
    assert "usage:" not in err


def run(capsys, *argv: str) -> str:
    assert main(list(argv)) == 0
    return capsys.readouterr().out


def test_hardware_named_topology(capsys):
    out = run(capsys, "ring", "2", "-b", "hardware", "-n", "2")
    assert out == (
        "--fpgalink=n00:acl0:ch1-n00:acl1:ch0 "
        "--fpgalink=n00:acl1:ch1-n00:acl0:ch0\n"
    )


def test_hardware_loopback_links_per_fpga(capsys):
    out = run(capsys, "loopback", "1", "-c", "1", "-b", "hardware")
    assert out == "--fpgalink=n00:acl0:ch0-n00:acl0:ch0\n"


def test_loopback_defaults_to_two_links(capsys):
    out = run(capsys, "loopback", "1", "-b", "hardware")
    assert out.split() == [
        "--fpgalink=n00:acl0:ch0-n00:acl0:ch0",
        "--fpgalink=n00:acl0:ch1-n00:acl0:ch1",
    ]


def test_emulation_loopback_uses_platform_links(capsys):
    out = run(capsys, "loopback", "1", "-b", "emulation", "-p", "n2s10")
    assert [l for l in out.splitlines() if l.startswith("mkfifo")] == [
        f"mkfifo rank0/link_i{link}_tx" for link in range(4)
    ]


def test_links_per_rank_removed():
    with pytest.raises(SystemExit):
        main(["loopback", "1", "-l", "2", "-b", "hardware"])


@pytest.mark.parametrize("flag", ["-n", "-c"])
@pytest.mark.parametrize("value", ["0", "-1", "x"])
def test_counts_must_be_positive_integers(capsys, flag, value):
    with pytest.raises(SystemExit):
        main(["ring", "2", "-b", "hardware", flag, value])
    assert "error: argument" in capsys.readouterr().err


def test_hardware_gui_url(capsys):
    out = run(capsys, "pair", "1", "-b", "hardware", "-g")
    assert out.startswith("https://pc2.github.io/fpgalink-gui/index.html?import=")


# The exact arguments the hardware CI jobs pass to changeFPGAlinks{,Xilinx}.
@pytest.mark.parametrize("topo, platform, expected", [
    ("xilinx_loopback.topo", "n2u280", 6),
    ("xilinx_pair.topo", "n2u280", 3),
    ("xilinx_ring.topo", "n2u280", 3),
    ("bittware_loopback.topo", "n2s10", 8),
    ("bittware_pair.topo", "n2s10", 4),
    ("bittware_adjacent.topo", "n2s10", 4),
    ("bittware_different.topo", "n2s10", 4),
])
def test_ci_invocations(capsys, topo, platform, expected):
    out = run(
        capsys, "-f", str(TOPO_DIR / topo), "-b", "hardware",
        "-p", platform,
    )
    args = out.split()
    assert len(args) == expected
    assert all(a.startswith("--fpgalink=") for a in args)


def test_emulation_with_bsp(capsys):
    out = run(
        capsys, "loopback", "1", "-c", "1",
        "-b", "emulation", "-d", "p", "-s", "bittware_s10",
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


def test_emulation_bsp_link_out_of_range(capsys):
    with raises_usage_error(capsys, "has links 0..3"):
        main([
            "loopback", "1", "-c", "5",
            "-b", "emulation", "-s", "bittware_s10",
        ])


@pytest.mark.parametrize("lpf, ok", [("4", True), ("3", False)])
def test_hardware_links_per_fpga(capsys, lpf, ok):
    argv = [
        "-f", str(TOPO_DIR / "bittware_pair.topo"), "-b", "hardware",
        "-n", "2", "-c", lpf,
    ]
    if ok:
        assert len(run(capsys, *argv).split()) == 4
    else:
        with raises_usage_error(capsys, "FPGAs have links 0..2"):
            main(argv)


def _topo(tmp_path, text: str) -> str:
    f = tmp_path / "t.topo"
    f.write_text(text)
    return str(f)


def test_platform_n2u280(capsys, tmp_path):
    out = run(capsys, "ring", "4", "-b", "hardware", "-p", "n2u280")
    assert out.split()[2] == "--fpgalink=n00:acl2:ch1-n01:acl0:ch0"
    assert run(capsys, "loopback", "1", "-b", "hardware",
               "-p", "n2u280").count("--fpgalink") == 2
    with raises_usage_error(capsys, "FPGAs have links 0..1"):
        main(["-f", _topo(tmp_path, "0.2 - 0.2\n"),
              "-b", "hardware", "-p", "n2u280"])


def test_platform_n2s10(capsys, tmp_path):
    out = run(capsys, "ring", "3", "-b", "hardware", "-p", "n2s10")
    assert out.split()[1] == "--fpgalink=n00:acl1:ch1-n01:acl0:ch0"
    assert run(capsys, "loopback", "1", "-b", "hardware",
               "-p", "n2s10").count("--fpgalink") == 4
    with raises_usage_error(capsys, "FPGAs have links 0..3"):
        main(["-f", _topo(tmp_path, "0.4 - 0.4\n"),
              "-b", "hardware", "-p", "n2s10"])


def test_platform_explicit_flags_override(capsys):
    out = run(
        capsys, "loopback", "4", "-b", "hardware",
        "-p", "n2u280", "-n", "1", "-c", "3",
    )
    assert out.split()[-1] == "--fpgalink=n03:acl0:ch2-n03:acl0:ch2"


def test_no_platform_defaults(capsys):
    out = run(capsys, "loopback", "4", "-c", "9", "-b", "hardware")
    assert out.split()[-1] == "--fpgalink=n01:acl0:ch8-n01:acl0:ch8"


def test_unknown_platform():
    with pytest.raises(SystemExit):
        main(["ring", "2", "-b", "hardware", "-p", "n3u55c"])


OPTIONS = [
    ("--file", "-f"), ("--backend", "-b"),
    ("--bsp", "-s"), ("--base-dir", "-d"), ("--platform", "-p"),
    ("--fpgas-per-node", "-n"), ("--links-per-fpga", "-c"),
    ("--gui-url", "-g"), ("--help", "-h"),
]


@pytest.mark.parametrize("long, short", OPTIONS, ids=[o[0] for o in OPTIONS])
def test_every_option_has_lower_and_upper_short_form(long, short):
    action = next(
        a for a in build_parser()._actions if long in a.option_strings
    )
    assert sorted(action.option_strings) == sorted(
        [long, short, short.upper()]
    )


def test_no_option_without_short_forms():
    long_options = {
        s for a in build_parser()._actions for s in a.option_strings
        if s.startswith("--")
    }
    assert long_options == {long for long, _ in OPTIONS}


@pytest.mark.parametrize("variant", ["long", "lower", "upper"])
def test_option_forms_are_equivalent(capsys, variant):
    def opt(long, short):
        return {"long": long, "lower": short, "upper": short.upper()}[variant]

    hw = run(
        capsys, "-f", str(TOPO_DIR / "xilinx_ring.topo"),
        opt("--backend", "-b"), "hardware", opt("--platform", "-p"),
        "n2u280", opt("--fpgas-per-node", "-n"), "2",
        opt("--links-per-fpga", "-c"), "2",
    )
    url = run(
        capsys, "loopback", "2", opt("--links-per-fpga", "-c"), "1",
        opt("--backend", "-b"), "hardware", opt("--gui-url", "-g"),
    )
    emu = run(
        capsys, "loopback", "1", opt("--links-per-fpga", "-c"), "1",
        opt("--backend", "-b"), "emulation", opt("--base-dir", "-d"), "p",
        opt("--bsp", "-s"), "bittware_s10",
    )
    assert hw == (
        "--fpgalink=n00:acl0:ch1-n00:acl1:ch0 "
        "--fpgalink=n00:acl1:ch1-n01:acl0:ch0 "
        "--fpgalink=n01:acl0:ch1-n00:acl0:ch0\n"
    )
    assert url.startswith("https://pc2.github.io/fpgalink-gui/")
    assert "ln -s link_i0_tx p/rank0/1" in emu.splitlines()


@pytest.mark.parametrize("flag", ["-h", "-H", "--help"])
def test_help(capsys, flag):
    with pytest.raises(SystemExit) as exc:
        main([flag])
    assert exc.value.code == 0
    assert "--links-per-fpga" in capsys.readouterr().out


def test_missing_topo_file(capsys, tmp_path):
    with raises_usage_error(capsys, "cannot read .*nope.topo: No such file"):
        main(["-f", str(tmp_path / "nope.topo"), "-b", "hardware"])


@pytest.mark.parametrize("text, match", [
    ("0.0 - 1.0\n0.0 - 2.0\n", "at most one"),
    ("star 4\n", "Unknown command"),
    ("0.0.0 - 1.1\n", "Invalid endpoint"),
])
def test_invalid_topo_file(capsys, tmp_path, text, match):
    with raises_usage_error(capsys, match):
        main(["-f", _topo(tmp_path, text), "-b", "emulation"])


@pytest.mark.parametrize("name", ["ring.json", "ring.JSON"])
def test_json_file(capsys, tmp_path, name):
    f = tmp_path / name
    f.write_text(topomux.to_json(topomux.ring(3)))
    assert run(capsys, "-f", str(f), "-b", "hardware", "-p", "n2u280") == run(
        capsys, "ring", "3", "-b", "hardware", "-p", "n2u280")


def test_json_stdin(capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(topomux.to_json(topomux.pair(2))))
    assert run(capsys, "-f", "-", "-b", "hardware") == run(
        capsys, "pair", "2", "-b", "hardware")


def test_invalid_json_file(capsys, tmp_path):
    f = tmp_path / "g.json"
    f.write_text("{")
    with raises_usage_error(capsys, "invalid JSON"):
        main(["-f", str(f), "-b", "hardware"])


def test_json_pipe_end_to_end(tmp_path):
    producer = (
        "import json, sys, networkx as nx\n"
        "g = nx.Graph(); g.add_edge((0, 1), (1, 0)); g.add_edge((1, 1), (0, 0))\n"
        "json.dump(nx.node_link_data(g, edges='edges'), sys.stdout)\n"
    )
    data = subprocess.run(
        [sys.executable, "-c", producer], capture_output=True, text=True,
        check=True,
    ).stdout
    out = subprocess.run(
        [sys.executable, "-m", "topomux", "-f", "-", "-b", "hardware",
         "-p", "n2s10"],
        input=data, capture_output=True, text=True, check=True,
    ).stdout
    assert out == (
        "--fpgalink=n00:acl0:ch1-n00:acl1:ch0 "
        "--fpgalink=n00:acl1:ch1-n00:acl0:ch0\n"
    )

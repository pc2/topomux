from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

import networkx as nx

from topomux import topologies
from topomux.backends.emulation import BSP_REGISTRY, EmulationBackend
from topomux.backends.hardware import PLATFORMS, HardwareBackend, NodeMapping

TOPOLOGIES = {
    "ring": topologies.ring,
    "reverse-ring": topologies.reverse_ring,
    "loopback": topologies.loopback,
    "pair": topologies.pair,
}


def _positive_int(value: str) -> int:
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an integer: {value!r}")
    if n < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {n}")
    return n


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="topomux",
        description="Generate FPGA communication topologies",
        add_help=False,
    )
    parser.add_argument(
        "--help", "-h", "-H",
        action="help",
        help="Show this help message and exit",
    )

    # Topology source: either a named topology or a file
    topo_group = parser.add_mutually_exclusive_group(required=True)
    topo_group.add_argument(
        "topology",
        nargs="?",
        choices=list(TOPOLOGIES.keys()),
        help="Standard topology type",
    )
    topo_group.add_argument(
        "--file", "-f", "-F",
        type=Path,
        dest="topo_file",
        help="Topology file: .topo, or node-link JSON if it ends in .json "
        "or is '-' (stdin)",
    )

    parser.add_argument(
        "num_ranks",
        nargs="?",
        type=int,
        help="Number of ranks (required for standard topologies)",
    )

    parser.add_argument(
        "--backend", "-b", "-B",
        choices=["emulation", "hardware"],
        required=True,
        help="Output backend",
    )

    # Emulation options
    parser.add_argument(
        "--bsp", "-s", "-S",
        choices=list(BSP_REGISTRY.keys()),
        default=None,
        help="Add fd-number symlinks per this BSP's id layout",
    )
    parser.add_argument(
        "--base-dir", "-d", "-D",
        type=Path,
        default=Path("."),
        help="Base directory for emulation links",
    )

    # Hardware options
    parser.add_argument(
        "--platform", "-p", "-P",
        choices=list(PLATFORMS.keys()),
        default=None,
        help="Set -n/--fpgas-per-node and -c/--links-per-fpga for this platform",
    )
    parser.add_argument(
        "--fpgas-per-node", "-n", "-N",
        type=_positive_int,
        default=None,
        help="FPGAs per physical node (default: 3, or the platform's)",
    )
    parser.add_argument(
        "--links-per-fpga", "-c", "-C",
        type=_positive_int,
        default=None,
        help="Links per FPGA: loopback loops all of them, hardware "
        "rejects links outside 0..N-1 (default: the platform's, else "
        "2 for loopback and no check)",
    )
    parser.add_argument(
        "--gui-url", "-g", "-G",
        action="store_true",
        help="Print fpgalink-gui URL",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return _run(parser, args)
    except ValueError as e:
        # Invalid topology or one the backend can't emit: one error line,
        # no traceback and no usage (the arguments themselves were fine).
        _fail(parser, str(e))


def _fail(parser: argparse.ArgumentParser, message: str) -> None:
    parser.exit(2, f"{parser.prog}: error: {message}\n")


def _load_file(path: Path) -> nx.Graph:
    if str(path) == "-":
        return topologies.from_json(sys.stdin)
    if path.suffix.lower() == ".json":
        return topologies.from_json(path)
    return topologies.from_file(path)


def _run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    mapping = PLATFORMS[args.platform] if args.platform else NodeMapping()
    # Explicit flags override the platform's values.
    overrides = {
        "fpgas_per_node": args.fpgas_per_node,
        "links_per_fpga": args.links_per_fpga,
    }
    mapping = replace(
        mapping, **{k: v for k, v in overrides.items() if v is not None},
    )

    # Build topology
    if args.topo_file:
        try:
            graph = _load_file(args.topo_file)
        except OSError as e:
            _fail(parser, f"cannot read {args.topo_file}: {e.strerror}")
    else:
        if args.num_ranks is None:
            parser.error("num_ranks is required for standard topologies")

        topo_fn = TOPOLOGIES[args.topology]

        if args.topology == "loopback":
            graph = topo_fn(
                args.num_ranks,
                links_per_rank=(
                    2 if mapping.links_per_fpga is None
                    else mapping.links_per_fpga
                ),
            )
        else:
            graph = topo_fn(args.num_ranks)

    # Emit output
    if args.backend == "hardware":
        backend = HardwareBackend(mapping=mapping)
        if args.gui_url:
            print(backend.emit_gui_url(graph))
        else:
            print(" ".join(backend.emit(graph)))

    elif args.backend == "emulation":
        bsp = BSP_REGISTRY[args.bsp]() if args.bsp else None
        backend = EmulationBackend(base_dir=args.base_dir, bsp=bsp)
        for action in backend.emit(graph):
            print(action)

    return 0

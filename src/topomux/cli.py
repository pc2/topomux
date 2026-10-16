from __future__ import annotations

import argparse
import sys
from pathlib import Path

from topomux import topologies
from topomux.backends.emulation import BSP_REGISTRY, EmulationBackend
from topomux.backends.hardware import HardwareBackend, NodeMapping

TOPOLOGIES = {
    "ring": topologies.ring,
    "reverse-ring": topologies.reverse_ring,
    "loopback": topologies.loopback,
    "pair": topologies.pair,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="topomux",
        description="Generate FPGA communication topologies",
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
        "--file", "-f",
        type=Path,
        dest="topo_file",
        help="Topology file (.topo)",
    )

    parser.add_argument(
        "num_ranks",
        nargs="?",
        type=int,
        help="Number of ranks (required for standard topologies)",
    )

    parser.add_argument(
        "--links-per-rank",
        type=int,
        default=2,
        help="Links per rank for loopback (default: 2)",
    )

    parser.add_argument(
        "--backend", "-b",
        choices=["emulation", "hardware"],
        required=True,
        help="Output backend",
    )

    # Emulation options
    parser.add_argument(
        "--bsp",
        choices=list(BSP_REGISTRY.keys()),
        default=None,
        help="Add fd-number symlinks per this BSP's id layout",
    )
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=Path("."),
        help="Base directory for emulation links",
    )

    # Hardware options
    parser.add_argument(
        "--fpgas-per-node",
        type=int,
        default=3,
        help="FPGAs per physical node (default: 3)",
    )
    parser.add_argument(
        "--links-per-fpga",
        type=int,
        default=None,
        help="Reject links outside 0..N-1 (default: no check)",
    )
    parser.add_argument(
        "--gui-url",
        action="store_true",
        help="Print fpgalink-gui URL",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Build topology
    if args.topo_file:
        graph = topologies.from_file(args.topo_file)
    else:
        if args.num_ranks is None:
            parser.error("num_ranks is required for standard topologies")

        topo_fn = TOPOLOGIES[args.topology]

        if args.topology == "loopback":
            graph = topo_fn(
                args.num_ranks,
                links_per_rank=args.links_per_rank,
            )
        else:
            graph = topo_fn(args.num_ranks)

    # Emit output
    if args.backend == "hardware":
        mapping = NodeMapping(
            fpgas_per_node=args.fpgas_per_node,
            links_per_fpga=args.links_per_fpga,
        )
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

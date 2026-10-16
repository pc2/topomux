from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

import networkx as nx

from topomux.topologies import validate


@dataclass
class NodeMapping:
    """Maps a flat rank index to nXX:aclY hardware coordinates.

    ``links_per_fpga`` is the number of links each FPGA has; ``None``
    disables the range check."""

    fpgas_per_node: int = 3
    links_per_fpga: int | None = None

    def node_id(self, rank: int) -> int:
        return rank // self.fpgas_per_node

    def acl_id(self, rank: int) -> int:
        return rank % self.fpgas_per_node

    def format(self, rank: int) -> str:
        return f"n{self.node_id(rank):02d}:acl{self.acl_id(rank)}"


PLATFORMS: dict[str, NodeMapping] = {
    # Noctua 2 Xilinx Alveo U280: 3 FPGAs per node, 2 links each
    "n2u280": NodeMapping(fpgas_per_node=3, links_per_fpga=2),
    # Noctua 2 Bittware 520N (Stratix 10): 2 FPGAs per node, 4 links each
    "n2s10": NodeMapping(fpgas_per_node=2, links_per_fpga=4),
}


class HardwareBackend:
    """Generates --fpgalink=... strings for any toolchain that consumes the
    Xilinx / oneAPI fpgalink syntax. Callers prepend their own tool name
    (changeFPGAlinks, changeFPGAlinksXilinx, ...)."""

    def __init__(self, mapping: NodeMapping | None = None):
        self.mapping = mapping or NodeMapping()

    def emit(self, graph: nx.Graph) -> list[str]:
        """Return list of --fpgalink=... strings, one per edge."""
        validate(graph)
        lpf = self.mapping.links_per_fpga
        if lpf is not None:
            for rank, link in graph.nodes:
                if link >= lpf:
                    raise ValueError(
                        f"Node {(rank, link)!r}: FPGAs have links "
                        f"0..{lpf - 1}"
                    )
        links: list[str] = []
        for (r1, l1), (r2, l2) in graph.edges:
            src = f"{self.mapping.format(r1)}:ch{l1}"
            dst = f"{self.mapping.format(r2)}:ch{l2}"
            links.append(f"--fpgalink={src}-{dst}")
        return links

    def emit_gui_url(self, graph: nx.Graph) -> str:
        """Return fpgalink-gui URL for visualization."""
        links_str = " ".join(self.emit(graph))
        encoded = quote(links_str, safe="")
        return (
            f"https://pc2.github.io/fpgalink-gui/index.html?import={encoded}"
        )

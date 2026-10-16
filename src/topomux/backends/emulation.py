from __future__ import annotations

import os
from pathlib import Path

import networkx as nx

from topomux.topologies import links as links_of, ranks, validate


class LinkNaming:
    """Per-rank directory layout: rank{R}/link_i{L}_{tx,rx}."""

    def rank_dir(self, base_dir: Path, rank: int) -> Path:
        return base_dir / f"rank{rank}"

    def tx_path(self, base_dir: Path, rank: int, link: int) -> Path:
        return self.rank_dir(base_dir, rank) / f"link_i{link}_tx"

    def rx_path(self, base_dir: Path, rank: int, link: int) -> Path:
        return self.rank_dir(base_dir, rank) / f"link_i{link}_rx"

    def directories(self, base_dir: Path, rank_ids: list[int]) -> list[Path]:
        return [self.rank_dir(base_dir, r) for r in rank_ids]


class BSP:
    """Maps a link index to the fd id a kernel IO-pipe struct declares."""

    name: str = "abstract"

    def input_id(self, link: int) -> int:
        raise NotImplementedError

    def output_id(self, link: int) -> int:
        raise NotImplementedError

    def num_links(self) -> int:
        raise NotImplementedError


class BittwareS10BSP(BSP):
    """bittware_s10 / 520N. chan_id positions in board_spec.xml:
        2L   -> kernel_input_chL   (id = 2L)
        2L+1 -> kernel_output_chL  (id = 2L+1)
    """

    name = "bittware_s10"

    def input_id(self, link: int) -> int:
        return 2 * link

    def output_id(self, link: int) -> int:
        return 2 * link + 1

    def num_links(self) -> int:
        return 4


BSP_REGISTRY: dict[str, type[BSP]] = {
    "bittware_s10": BittwareS10BSP,
}


def _symlink_target(target: Path, link: Path) -> str:
    """Absolute base-dir → absolute target. Relative base-dir → relative target."""
    if target.is_absolute():
        return str(target)
    return os.path.relpath(target, link.parent)


class EmulationBackend:
    """Emit shell commands that set up unix FIFOs and symlinks for software
    emulation. Pure: never touches the filesystem. Caller pipes stdout to
    `bash` to actually create the files."""

    def __init__(
        self,
        base_dir: Path,
        naming: LinkNaming | None = None,
        bsp: BSP | None = None,
    ):
        self.naming = naming or LinkNaming()
        self.base_dir = Path(base_dir)
        self.bsp = bsp

    def emit(self, graph: nx.Graph) -> list[str]:
        """Return the mkdir/mkfifo/ln-s shell commands for the graph."""
        validate(graph)
        actions: list[str] = []
        rank_ids = ranks(graph)

        for d in self.naming.directories(self.base_dir, rank_ids):
            actions.append(f"mkdir -p {d}")

        created_fifos: set[Path] = set()

        def _ensure_tx_fifo(rank: int, link: int) -> Path:
            tx = self.naming.tx_path(self.base_dir, rank, link)
            if tx not in created_fifos:
                actions.append(f"mkfifo {tx}")
                created_fifos.add(tx)
            return tx

        for (r_a, l_a), (r_b, l_b) in graph.edges:
            is_self_loop = (r_a, l_a) == (r_b, l_b)

            tx_a = _ensure_tx_fifo(r_a, l_a)
            if not is_self_loop:
                tx_b = _ensure_tx_fifo(r_b, l_b)

            rx_a = self.naming.rx_path(self.base_dir, r_a, l_a)
            if is_self_loop:
                target = _symlink_target(tx_a, rx_a)
                actions.append(f"ln -s {target} {rx_a}")
            else:
                target_a = _symlink_target(tx_b, rx_a)
                actions.append(f"ln -s {target_a} {rx_a}")

                rx_b = self.naming.rx_path(self.base_dir, r_b, l_b)
                target_b = _symlink_target(tx_a, rx_b)
                actions.append(f"ln -s {target_b} {rx_b}")

        if self.bsp is not None:
            for rank in rank_ids:
                for link in links_of(graph, rank):
                    # Unused link: no FIFO exists, so no fd symlinks either.
                    if nx.is_isolate(graph, (rank, link)):
                        continue
                    tx = self.naming.tx_path(self.base_dir, rank, link)
                    rx = self.naming.rx_path(self.base_dir, rank, link)
                    rank_dir = self.naming.rank_dir(self.base_dir, rank)

                    tx_fd = rank_dir / str(self.bsp.output_id(link))
                    rx_fd = rank_dir / str(self.bsp.input_id(link))

                    actions.append(f"ln -s {tx.name} {tx_fd}")
                    actions.append(f"ln -s {rx.name} {rx_fd}")

        return actions

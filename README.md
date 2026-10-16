# topomux

FPGA network topology generator built on NetworkX. Defines topologies once, emits shell commands for either hardware (`--fpgalink=...` strings) or emulation (`mkdir`/`mkfifo`/`ln -s` strings). Both backends are pure: they print to stdout and never touch the filesystem. Pipe to `bash` to apply.

The graph's nodes are `(rank, link)` tuples, the emulation filesystem layout is `rank{R}/link_i{L}_{tx,rx}`, and the hardware backend emits `--fpgalink=...` strings. Every link is bidirectional at the filesystem level (always has a `_tx` FIFO + an `_rx` symlink wired by the graph edges).

## Install

With `uv`:

```bash
uv venv --python 3.14
source .venv/bin/activate
uv pip install git+https://github.com/pc2/topomux
# or editable from a local checkout:
uv pip install -e /path/to/topomux
```

Or the repo's own `make` using traditional venv:

```bash
source env.sh
make venv
source .venv/bin/activate
```

## Tests

`make venv` installs the `test` extra.
Otherwise install it with `uv pip install -e ".[test]"`.

```bash
pytest
```

The unit tests run on CPU only and need no FPGAs.
In CI they run before the hardware jobs, which only start if the unit tests pass.

## CLI

Four topologies ship:

| Name           | Edge |
|----------------|------|
| `ring`         | `(r, 1) <-> ((r+1) % n, 0)` |
| `reverse-ring` | `(r, 0) <-> ((r+1) % n, 1)` |
| `loopback`     | `(r, L) <-> (r, L)` for each rank and link |
| `pair`         | `(r, 0) <-> (r, 1)` within each rank |

Every option has a lowercase and an uppercase short form with the same meaning (`-p` = `-P` = `--platform`).
The examples use the lowercase forms.

| Short       | Long                 | Applies to | Meaning |
|-------------|----------------------|------------|---------|
| `-f`, `-F`  | `--file`             | all        | Read the topology from a `.topo` file, or [node-link JSON](#node-link-json) if it ends in `.json` or is `-` (stdin) |
| `-b`, `-B`  | `--backend`          | all        | `hardware` or `emulation` |
| `-p`, `-P`  | `--platform`         | all        | Set `-n` and `-c` for a known system, see [Platforms](#platforms) |
| `-n`, `-N`  | `--fpgas-per-node`   | hardware   | FPGAs per physical node (default: 3) |
| `-c`, `-C`  | `--links-per-fpga`   | all        | Links each FPGA has: `loopback` loops all of them (default: 2), the hardware backend rejects links outside `0..N-1` (default: no check) |
| `-g`, `-G`  | `--gui-url`          | hardware   | Print the fpgalink-gui URL instead |
| `-d`, `-D`  | `--base-dir`         | emulation  | Base directory for the pipes (default: `.`) |
| `-s`, `-S`  | `--bsp`              | emulation  | Add fd-number symlinks for this BSP, see [BSP overlay](#bsp-overlay) |
| `-h`, `-H`  | `--help`             |            | Show help |

```bash
# Hardware: emits --fpgalink=... flags on stdout, space-separated.
# Prepend the toolchain's link tool:
changeFPGAlinks       $(topomux ring 2 -b hardware -p n2s10)
changeFPGAlinksXilinx $(topomux ring 3 -b hardware -p n2u280)

# Without a platform, or to override its values: -n FPGAs per node, -c links per FPGA
topomux ring 4 -b hardware -n 1 -c 2

# Loopback on every link of the platform (4 on n2s10)
topomux loopback 2 -b hardware -p n2s10

# From topology file
topomux -f topologies/xilinx_ring.topo -b hardware -p n2u280

# From a NetworkX graph as node-link JSON, as a file or on stdin
topomux -f ring.json -b hardware -p n2u280
python make_topology.py | topomux -f - -b hardware -p n2u280

# Emulation: prints mkdir/mkfifo/ln-s commands. Pipe to bash to apply.
topomux ring 4 -b emulation -d /tmp/pipes
topomux ring 4 -b emulation -d /tmp/pipes | bash

# Emulation with a BSP overlay (adds symlinks according to BSP's id layout)
topomux reverse-ring 4 -b emulation -s <name> -d /tmp/pipes | bash

# FPGA-Link GUI URL
topomux ring 3 -b hardware -g
```

## Library

```python
from pathlib import Path

import topomux

# Standard topologies - pick direction by function name
g = topomux.ring(4)
g = topomux.reverse_ring(4)
g = topomux.loopback(3, links_per_rank=2)
g = topomux.pair(3)

# From file
g = topomux.from_file("topologies/some.topo")
g = topomux.from_json("ring.json")   # node-link JSON, path or open file

# Serialize for the CLI (-f ring.json or -f -)
Path("ring.json").write_text(topomux.to_json(g))

# Arbitrary edges
g = topomux.from_edge_list([
    ((0, 0), (1, 1)),
    ((1, 0), (2, 1)),
    ((2, 0), (0, 1)),
])

# Any NetworkX graph whose nodes are (rank, link) int tuples
import networkx as nx
g = nx.Graph()
g.add_edge((0, 1), (1, 0))
g.add_edge((1, 1), (0, 0))

# Hardware output (returns list of --fpgalink=... strings)
hw = topomux.HardwareBackend(topomux.PLATFORMS["n2u280"])
# or explicitly:
hw = topomux.HardwareBackend(
    topomux.NodeMapping(fpgas_per_node=3, links_per_fpga=2),
)
print(" ".join(hw.emit(g)))
print(hw.emit_gui_url(g))

# Emulation output (returns list of mkdir/mkfifo/ln-s commands)
emu = topomux.EmulationBackend(base_dir="/tmp/pipes")
for action in emu.emit(g):
    print(action)

# Emulation output (with BSP overlay)
emu = topomux.EmulationBackend(
    base_dir="/tmp/pipes",
    bsp=topomux.BittwareS10BSP(),
)
for action in emu.emit(g):
    print(action)
```

The topology constructors are convenience helpers.
Both backends accept any `nx.Graph` directly, so you can build or transform a topology with regular NetworkX operations and pass it to `emit()`.
Nodes must be `(rank, link)` tuples of non-negative integers (`int` or e.g. `numpy.int64`, but not `bool`).
`emit()` calls `topomux.validate(g)` and raises `ValueError` if it is not valid.
Each edge is one bidirectional link, and a self-loop `(r, L) <-> (r, L)` is a loopback.
Each `(rank, link)` node must appear in at most one edge.
A node without edges is possible to setup, and still gets an rank directory in the emulation backendend.
Node and edge attributes are ignored.

## Platforms

`-p` sets `-n` (FPGAs per node) and `-c` (links per FPGA) for a known system.
Explicit `-n` or `-c` flags override the platform's values.

| Platform | Hardware | FPGAs per node | Links per FPGA |
|----------|----------|----------------|----------------|
| `n2u280` | Noctua 2, Xilinx Alveo U280 | 3 | 2 |
| `n2s10`  | Noctua 2, Bittware 520N (Stratix 10) | 2 | 4 |

In the library, `topomux.PLATFORMS` maps each name to its `NodeMapping`.

## Node-link JSON

`-f` reads [node-link JSON](https://networkx.org/documentation/stable/reference/readwrite/generated/networkx.readwrite.json_graph.node_link_data.html) when the file name ends in `.json` or is `-` (stdin).
Write it with `topomux.to_json(g)` or with plain NetworkX:

```python
import json, sys
import networkx as nx

g = nx.Graph()
g.add_edge((0, 1), (1, 0))
g.add_edge((1, 1), (0, 0))
json.dump(nx.node_link_data(g, edges="edges"), sys.stdout)
```

Node ids are `[rank, link]` lists and are loaded as `(rank, link)` tuples.
Nodes without edges are kept.
The same rules apply as for any graph passed to the library (see [Library](#library)); directed graphs and the pre-3.4 `"links"` key are rejected.

## Topology File Format

`.topo` files support edge lists and shorthand commands. Comments with `#`.

```
# Shorthand
ring 4
reverse-ring 4
loopback 3 4        # 3 ranks, 4 links per rank
pair 3

# Explicit edges: rank.link - rank.link
0.0 - 1.1
2.0 - 0.1
```

## Emulation layout

For every `(rank, link)` node the graph uses, the emulation backend creates:

```
{base_dir}/rank{R}/link_i{L}_tx    FIFO
{base_dir}/rank{R}/link_i{L}_rx    symlink wired by the graph edges
```

## BSP overlay

Intel BSPs IO-pipes are expecting a file in the process's cwd named after the id matching the number in the `board_spec.xml`.

For these runtimes, topomux emits an additional *fd-number* symlink layer via `-s`. For every `(rank, link)` node that is part of an edge:

```
{base_dir}/rank{R}/{bsp.output_id(L)} -> link_i{L}_tx
{base_dir}/rank{R}/{bsp.input_id (L)} -> link_i{L}_rx
```

A `BSP` describes *pure board layout*: `input_id(link)` and `output_id(link)` return the ids the hardware platform assigns to each link direction.
`num_links()` is the number of links the board has.
With a BSP set, `emit()` raises `ValueError` for any node whose link is outside `0..num_links()-1`.

### Shipped BSPs

`bittware_s10` (Bittware 520N, Stratix 10 p520_max_sg280l). The BSP lists 4 bidirectional channels in `board_spec.xml` with the id assignments that fall out of the chan_id positions:

```python
class BittwareS10BSP(BSP):
    name = "bittware_s10"

    def input_id(self, link):  return 2 * link        # kernel_input_chL  = id 2L
    def output_id(self, link): return 2 * link + 1    # kernel_output_chL = id 2L+1
    def num_links(self):       return 4
```

Then `topomux <topology> N -b emulation -s bittware_s10` works end-to-end.

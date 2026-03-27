# Stockfish Instrumentation

Version 1.0

Copyright 2026 Maxim Masiutin.

License: GPL-3.0 (see [LICENSE](LICENSE))

Tools for measuring correction history write delta distributions in Stockfish.
Instruments the `update_correction_history` function to record how often each
correction table write produces zero change, small deltas, or large deltas.

## Building the Instrumented Binary

The instrumentation is maintained on the
[instrument-shared-deltas](https://github.com/maximmasiutin/Stockfish/tree/instrument-shared-deltas)
branch of the Stockfish fork.

### Quick Start

```bash
git clone https://github.com/maximmasiutin/Stockfish.git
cd Stockfish
git checkout instrument-shared-deltas
cd src
make -j profile-build ARCH=x86-64-avx512icl COMP=gcc
```

Replace `ARCH` with your target architecture. On Windows with MSYS2:

```bash
make -j profile-build ARCH=x86-64-avx512icl COMP=mingw
```

### Applying Instrumentation to Other Branches

A pre-generated patch file is included in this repository: `instrument-shared-deltas.patch`.
It covers `src/search.cpp` and `src/uci.cpp`.

```bash
# Apply to a target branch in any Stockfish fork
cd /path/to/target-repo
git checkout target-branch
git apply /path/to/instrument-shared-deltas.patch

# Build with PGO (profile-build recommended for accurate results)
cd src
make -j profile-build ARCH=x86-64-avx512icl COMP=mingw   # Windows/MSYS2
# or
make -j profile-build ARCH=x86-64-avx512icl COMP=gcc  # Linux
```

If the patch does not apply cleanly (due to upstream changes in the target branch),
apply it with `--reject` to get partial hunks, then apply the remaining changes
manually by following the descriptions in "How It Works" below.

Use standard `profile-build` (not a clean-profile + instrumented-rebuild approach,
which causes 5x slowdown due to PGO profile mismatch).

To regenerate the patch from the source branch:

```bash
cd /path/to/maximmasiutin-Stockfish
git diff master..instrument-shared-deltas -- src/search.cpp src/uci.cpp > instrument-shared-deltas.patch
```

## Running the Sweep

Requires Python >= 3.12.

`run_delta_sweep.py` runs the instrumented binary at each bench depth and
produces a summary table plus optional raw CSV data.

### Usage

```bash
# Basic: depths 1-18 with 8 threads
python run_delta_sweep.py --exe ./stockfish --from 1 --to 18

# Save both summary and raw CSV
python run_delta_sweep.py --exe ./stockfish --from 1 --to 18 \
    -o results.txt --csv results.csv

# Custom thread count
python run_delta_sweep.py --exe ./stockfish --from 1 --to 10 -t 4
```

### Output Format

Summary table (stdout and -o file):

```text
Depth |   pawnCorr |   minorCorr |   nonpawnW |   nonpawnB |   contCorr2 |   contCorr4 |   Mean |    TotalWrites |      Time
-----------------------------------------------------------------------------------------------------------------------------
    1 |       2.4% |        2.4% |       2.4% |       2.4% |       57.4% |       63.5% |  21.7% |          5,352 |      1.6s
    2 |       3.8% |        7.7% |       4.1% |       6.1% |       37.7% |       42.6% |  17.0% |         16,518 |      1.7s
```

Raw CSV (--csv file):

```csv
depth,table,total_writes,elapsed_s,d0,d1,d2,d3,d4_5,d6_9,d10_19,d20_49,d50_99,d100_199,d200p
1,pawnCorr,892,1.6,2.4664,7.2869,...
```

The "d0" column shows the percentage of writes that produce zero value change.
TotalWrites is the sum across all 6 correction tables.
Time/elapsed_s is the wall-clock time in seconds for the bench run at that depth.
Time roughly doubles every 2-3 depths; depths 22+ can take minutes to hours each.

### Delta Bins

| Bin | Delta Range |
|-----|-------------|
| d0 | 0 (no change) |
| d1 | 1 |
| d2 | 2 |
| d3 | 3 |
| d4_5 | 4-5 |
| d6_9 | 6-9 |
| d10_19 | 10-19 |
| d20_49 | 20-49 |
| d50_99 | 50-99 |
| d100_199 | 100-199 |
| d200p | 200+ |

### Correction Tables

| Table | Description |
|-------|-------------|
| pawnCorr | Pawn structure correction |
| minorCorr | Minor piece correction |
| nonpawnW | Non-pawn white correction |
| nonpawnB | Non-pawn black correction |
| contCorr2 | Continuation correction (2 plies back) |
| contCorr4 | Continuation correction (4 plies back) |

## How It Works

The instrumentation wraps each correction history write in `update_correction_history()`.
Before calling `entry << bonus`, it computes what the new value would be using the
gravity formula, records `abs(new_value - old_value)` into a histogram bin, then
performs the normal write.

Counters are thread-local (no contention on the hot path). Each worker thread
copies its accumulated counters to a fixed slot after finishing each bench position.
At the end of bench, `print_delta_report()` aggregates all slots and outputs CSV
to stdout.

Stderr is suppressed during bench to avoid pipe buffer issues at high depths
(depth 22+ produces gigabytes of `info` lines over 51 bench positions).

## Typical Results

At standard Fishtest time controls (median depth 15-20), the zero-delta rate
for correction tables is 6-15% for the four correction tables and 8-17% for
the two continuation correction tables. At higher depths (20+), zero-delta
rates increase significantly as tables saturate.

## ContinuationCorrectionHistory Occupancy

A separate instrumentation (`instrument-contcorr-occupancy.patch`) measures
how many entries of the per-worker `continuationCorrectionHistory` table are
non-zero after a bench run.  The table is a 4D array indexed by
`[outer_piece][outer_to][inner_piece][inner_to]` (16x64x16x64 = 1,048,576
entries per worker).  Occupancy answers: at a given depth and thread count,
what fraction of these entries have been written at least once?

### Building the Occupancy Instrumented Binary

Apply `instrument-contcorr-occupancy.patch` to any Stockfish branch:

```bash
cd /path/to/Stockfish
git apply /path/to/instrument-contcorr-occupancy.patch
cd src
make -j profile-build ARCH=x86-64-avxvnni COMP=mingw   # Windows/MSYS2
```

### Running the Occupancy Sweep

```bash
# Depths 1-12, default thread counts [1, 4, 8, 10, 12, 14, 16, 18]
python run_contcorr_occupancy.py --exe ./stockfish --to 12

# Custom threads, save summary and CSV
python run_contcorr_occupancy.py --exe ./stockfish --to 18 \
    --threads 1 4 8 16 -o results.txt --csv raw.csv
```

### Occupancy Output Format

Summary table (stdout):

```text
Depth |      1T |      4T |      8T |    10T |    12T |    14T |    16T |    18T |   RowTime
---------------------------------------------------------------------------------------------
    1 |   0.12% |   0.12% |   0.13% |  0.13% |  0.14% |  0.14% |  0.14% |  0.15% |     50.1s
```

Raw CSV (--csv):

```csv
depth,nthreads,total_entries,sum_occupied,occupancy_pct,elapsed_s,t0_occupied,...
1,1,1048576,1234,0.12,5.2,1234
```

Each `occ,` line in the binary's stdout contains per-thread occupied counts.

### Shared Module

Common subprocess execution logic is in `shared/bench_runner.py`.  Both
`run_delta_sweep.py` and `run_contcorr_occupancy.py` can import from it:

```python
from shared.bench_runner import run_bench
lines, timed_out = run_bench("./stockfish", depth=10, threads=8)
```

## License

GPL-3.0, same as Stockfish.

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

## ContinuationCorrectionHistory Thread Overlap

A separate instrumentation (`instrument-contcorr-occupancy.patch`) measures
per-entry thread overlap in the `continuationCorrectionHistory` table.
For each of the 1,048,576 entries (16x64x16x64), a bitmask records which
threads wrote to that entry.  At the end of the run, the popcount distribution
shows how many entries were written by 1 thread, 2 threads, ..., N threads.

This data answers the key question for contCorrHist sharing:
what fraction of entries are contested by multiple threads?

The instrumentation tracks ss-2 and ss-4 writes separately (per-ply breakdown).

### Building the Overlap Instrumented Binary

Apply `instrument-contcorr-occupancy.patch` to any Stockfish branch:

```bash
cd /path/to/Stockfish
git apply /path/to/instrument-contcorr-occupancy.patch
cd src
make -j profile-build ARCH=x86-64-avxvnni COMP=mingw   # Windows/MSYS2
```

The patch modifies `src/search.cpp`, `src/search.h`, and `src/uci.cpp`.

### Running the Overlap Sweep

```bash
# Bench mode: depth 16-22, default threads [1, 2, 4, 8, 10, 12, 14, 16, 18]
python run_occupancy_sweep.py --exe ./stockfish --from 16 --to 22

# Book mode: positions from EPD file at fixed depth
python run_occupancy_sweep.py --exe ./stockfish --book positions.epd \
    --depth 20 -n 30 --threads 1 2 4 8

# Save summary and raw CSV
python run_occupancy_sweep.py --exe ./stockfish --depth 16 \
    --threads 1 2 4 8 -o results.txt --csv raw.csv
```

### Shared Modules

Common logic is in `shared/`:

```python
from shared.bench_runner import run_bench     # bench-mode subprocess
```

## NMP Correction Value Instrumentation

Separate instrumented binary (`instrument-nmp-signals-v2` branch) that measures
correction value distributions at each NMP node by depth. Outputs 32cp-bin
histograms for computing activation rates at various thresholds (128, 192, 256,
288cp).

### CRITICAL: One Position Per Run

**Never use `bench` with multiple positions for NMP instrumentation.** The
per-depth counters accumulate across all positions in a single bench run,
producing blended rates that do not reflect any individual position's behavior.
This can overestimate activation rates by 10x or more.

Always run one position per stockfish invocation. Use `run_nmp_perpos.py` which
handles this automatically. Save the EPD file used for reproducibility.

### NMP Instrumentation Scripts

| Script | Description |
|--------|-------------|
| `run_nmp_perpos.py` | Runs instrumented binary on each position separately (one exe run per FEN). Uses `shared.bench_runner`. |
| `aggregate_nmp_perpos.py` | Aggregates per-position CSV into per-depth totals for `compute_nmp_freq_table.py`. |
| `compute_nmp_freq_table.py` | Computes activation rates at thresholds 128/192/256/288/320/384cp from aggregated v2 CSV. |

### NMP Usage

```bash
# 1. Create EPD file with test positions (save for reproducibility)
# 2. Run per-position instrumentation
python run_nmp_perpos.py path/to/instrument-nmp-v2.exe positions.epd output.csv --depth 26

# 3. Aggregate across positions (per-depth totals)
python aggregate_nmp_perpos.py output.csv --summary > aggregated.csv

# 4. Compute activation rate tables
python compute_nmp_freq_table.py aggregated.csv
```

## License

GPL-3.0, same as Stockfish.

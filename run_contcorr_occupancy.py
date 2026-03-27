#!/usr/bin/env python3
"""Sweep ContinuationCorrectionHistory occupancy by depth and thread count.

Version 1.0
Copyright 2026 Maxim Masiutin.
License: GPL-3.0

Requires an instrumented binary built from instrument-contcorr-occupancy.patch.
The patch adds per-worker non-zero entry counting to search.cpp and calls
print_occupancy_report() from uci.cpp after each bench run.  The report is
emitted as a CSV line beginning with "occ," to stdout.

Usage:
  python run_contcorr_occupancy.py --exe ./stockfish --from 1 --to 12
  python run_contcorr_occupancy.py --exe ./stockfish --to 18 \\
      --threads 1 4 8 16 -o results.txt --csv raw.csv

Output:
  Summary table: rows = depth, columns = thread counts, cell = occupancy %.
  CSV (--csv):   one row per (depth, thread_count) with per-thread counts.
"""

import argparse
import csv
import sys
import time
from pathlib import Path

# Allow running from any directory or as a module
sys.path.insert(0, str(Path(__file__).parent))
from shared.bench_runner import DEFAULT_EXE, DEFAULT_TIMEOUT_S, run_bench  # pylint: disable=wrong-import-position

DEFAULT_THREAD_COUNTS = [1, 4, 8, 10, 12, 14, 16, 18]

OccRow = dict[str, int | float | str]


def parse_occ_line(line: str) -> OccRow | None:
    """Parse an instrumented binary 'occ,...' CSV line.

    Format emitted by print_occupancy_report() in search.cpp:
        occ,depth,nthreads,total_entries,sum_occupied,occupancy_pct[,tN_occupied...]

    Returns a dict with typed fields, or None if the line is not an occ line.
    """
    if not line.startswith("occ,"):
        return None
    parts = line.split(",")
    if len(parts) < 6:
        return None
    try:
        row: OccRow = {
            "depth": int(parts[1]),
            "nthreads": int(parts[2]),
            "total_entries": int(parts[3]),
            "sum_occupied": int(parts[4]),
            "occupancy_pct": float(parts[5]),
        }
        for i, val in enumerate(parts[6:]):
            row[f"t{i}_occupied"] = int(val)
        return row
    except (ValueError, IndexError):
        return None


def _build_csv_fieldnames(max_threads: int) -> list[str]:
    base = [
        "depth",
        "nthreads",
        "total_entries",
        "sum_occupied",
        "occupancy_pct",
        "elapsed_s",
    ]
    per_thread = [f"t{i}_occupied" for i in range(max_threads)]
    return base + per_thread


def main() -> (
    None
):  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
    """Entry point: parse arguments, run sweep, display and save results."""
    parser = argparse.ArgumentParser(
        description="Sweep contCorrHist occupancy by depth and thread count",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--exe",
        default=DEFAULT_EXE,
        help=f"Path to instrumented Stockfish binary (default: {DEFAULT_EXE})",
    )
    parser.add_argument(
        "--from",
        dest="from_depth",
        type=int,
        default=1,
        help="Starting depth (default: 1)",
    )
    parser.add_argument(
        "--to", type=int, default=12, help="Maximum depth (default: 12)"
    )
    parser.add_argument(
        "--threads",
        nargs="+",
        type=int,
        default=DEFAULT_THREAD_COUNTS,
        metavar="N",
        help=f"Thread counts to test (default: {DEFAULT_THREAD_COUNTS})",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_S,
        help=f"Per-bench timeout in seconds (default: {DEFAULT_TIMEOUT_S})",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        help="Save summary table to .txt file (flushed per row)",
    )
    parser.add_argument(
        "--csv",
        type=str,
        default=None,
        help="Save raw occupancy data to CSV file (flushed per row)",
    )
    args = parser.parse_args()

    thread_counts: list[int] = sorted(set(args.threads))
    max_threads = max(thread_counts)

    outf = (
        open(  # noqa: SIM115  # pylint: disable=consider-using-with
            args.output,
            "w",
            newline="\n",
            encoding="utf-8",
        )
        if args.output
        else None
    )

    csvf = None
    csvw: csv.DictWriter[str] | None = None
    if args.csv:
        fieldnames = _build_csv_fieldnames(max_threads)
        csvf = open(  # noqa: SIM115  # pylint: disable=consider-using-with
            args.csv,
            "w",
            newline="",
            encoding="utf-8",
        )
        csvw = csv.DictWriter(csvf, fieldnames=fieldnames, extrasaction="ignore")
        csvw.writeheader()
        csvf.flush()

    def emit(line: str) -> None:
        print(line, flush=True)
        if outf:
            outf.write(line + "\n")
            outf.flush()

    # Build summary header: depth | 1T | 4T | ... | time
    col_headers = " | ".join(f"{t:>7}T" for t in thread_counts)
    header = f"{'Depth':>5} | {col_headers} | {'RowTime':>9}"
    sep = "-" * len(header)

    try:
        emit(header)
        emit(sep)

        for depth in range(args.from_depth, args.to + 1):
            row_t0 = time.time()
            occ_by_threads: dict[int, float] = {}

            for threads in thread_counts:
                lines, timed_out = run_bench(
                    args.exe,
                    depth,
                    threads,
                    args.timeout,
                    progress_prefix=f"depth={depth}",
                )
                elapsed = time.time() - row_t0

                if timed_out:
                    occ_by_threads[threads] = float("nan")
                    continue

                for line in lines:
                    parsed = parse_occ_line(line)
                    if parsed is None:
                        continue
                    pct = float(parsed["occupancy_pct"])
                    occ_by_threads[threads] = pct
                    if csvw and csvf:
                        parsed["elapsed_s"] = round(elapsed, 1)
                        csvw.writerow(parsed)
                        csvf.flush()
                    break

            row_elapsed = time.time() - row_t0
            pct_cells = " | ".join(
                (
                    f"{occ_by_threads[t]:>7.2f}%"
                    if t in occ_by_threads
                    and not (occ_by_threads[t] != occ_by_threads[t])
                    else f"{'TIMEOUT':>8}"
                )
                for t in thread_counts
            )
            emit(f"{depth:>5} | {pct_cells} | {row_elapsed:>8.1f}s")

    finally:
        if outf:
            outf.close()
        if csvf:
            csvf.close()

    if args.output:
        print(f"\nSaved summary to {args.output}", flush=True)
    if args.csv:
        print(f"Saved raw CSV to {args.csv}", flush=True)


if __name__ == "__main__":
    main()

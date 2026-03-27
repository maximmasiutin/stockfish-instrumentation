#!/usr/bin/env python3
"""Sweep ContinuationCorrectionHistory thread overlap by depth and thread count.

Version 2.0
Copyright 2026 Maxim Masiutin.
License: GPL-3.0

Requires an instrumented binary built from instrument-contcorr-occupancy.patch.
The patch records per-entry thread bitmasks for contCorrHist writes and outputs
popcount distributions as CSV lines beginning with "overlap," to stdout.

Two modes:
  bench:  uses the built-in bench command (51 positions, fixed depth)
  book:   uses UCI protocol with positions from an EPD book file

Usage:
  # Bench mode (default): depth sweep with thread count sweep
  python run_contcorr_occupancy.py --exe ./stockfish --from 16 --to 22

  # Book mode: positions from EPD file, fixed depth
  python run_contcorr_occupancy.py --exe ./stockfish --book positions.epd \\
      --depth 20 -n 30

  # Custom thread counts
  python run_contcorr_occupancy.py --exe ./stockfish --from 16 --to 20 \\
      --threads 1 2 4 8

Output:
  Summary table: rows = depth, columns = thread counts, cell = overlap %.
  Overlap % = fraction of written entries hit by >= 2 threads.
  CSV (--csv): one row per (depth, threads, ply) with full popcount distribution.
"""

import argparse
import csv
import random
import sys
import time
from pathlib import Path

# Allow running from any directory or as a module
sys.path.insert(0, str(Path(__file__).parent))
from shared.bench_runner import (  # pylint: disable=wrong-import-position
    DEFAULT_EXE,
    DEFAULT_TIMEOUT_S,
    run_bench,
)
from shared.uci_engine import UCIEngine  # pylint: disable=wrong-import-position

DEFAULT_THREAD_COUNTS = [1, 2, 4, 8, 10, 12, 14, 16, 18]
MAX_POP = 32

OverlapRow = dict[str, int | float | str]


def parse_overlap_line(line: str) -> OverlapRow | None:
    """Parse an instrumented binary 'overlap,...' CSV line.

    Format: overlap,<ply>,<total_entries>,<pop0>,<pop1>,...,<pop32>

    Returns a dict with typed fields, or None if the line is not an overlap line.
    """
    if not line.startswith("overlap,"):
        return None
    parts = line.split(",")
    if len(parts) < 4:
        return None
    try:
        ply = int(parts[1])
        total = int(parts[2])
        pops = [int(x) for x in parts[3:]]
        written = total - pops[0] if pops else 0
        overlapped = sum(pops[2:]) if len(pops) > 2 else 0
        overlap_pct = (overlapped / written * 100.0) if written > 0 else 0.0
        written_pct = (written / total * 100.0) if total > 0 else 0.0
        mean_pop = 0.0
        if written > 0:
            weighted = sum(k * pops[k] for k in range(1, len(pops)))
            mean_pop = weighted / written

        row: OverlapRow = {
            "ply": ply,
            "total_entries": total,
            "written": written,
            "written_pct": round(written_pct, 4),
            "overlapped": overlapped,
            "overlap_pct": round(overlap_pct, 2),
            "mean_pop": round(mean_pop, 3),
        }
        for k, val in enumerate(pops):
            row[f"pop{k}"] = val
        return row
    except (ValueError, IndexError):
        return None


def load_book_positions(book_path: str, n: int, seed: int | None) -> list[str]:
    """Load n random FEN positions from an EPD file."""
    lines: list[str] = []
    with open(book_path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            raw = raw.strip()
            if raw and not raw.startswith("#"):
                lines.append(raw)
    rng = random.Random(seed)
    if n < len(lines):
        lines = rng.sample(lines, n)
    fens: list[str] = []
    for epd in lines:
        parts = epd.split()
        if len(parts) >= 4:
            fen = " ".join(parts[:4])
            if len(parts) < 6 or not parts[4].isdigit():
                fen += " 0 1"
            else:
                fen += " " + parts[4] + " " + (parts[5] if len(parts) > 5 else "1")
            fens.append(fen)
    return fens


def run_bench_overlap(
    exe: str, depth: int, threads: int, timeout_s: int
) -> list[OverlapRow]:
    """Run bench and parse overlap lines."""
    lines, timed_out = run_bench(
        exe, depth, threads, timeout_s, progress_prefix=f"d={depth} t={threads}"
    )
    if timed_out:
        return []
    results: list[OverlapRow] = []
    for line in lines:
        parsed = parse_overlap_line(line)
        if parsed is not None:
            # Skip empty reports (all pop0 = total, from quit hook)
            if int(parsed.get("written", 0)) > 0:
                results.append(parsed)
    if not results:
        print(
            f"  Warning: bench completed but no overlap data (d={depth} t={threads})",
            file=sys.stderr,
            flush=True,
        )
    return results


def run_book_overlap(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    exe: str,
    depth: int,
    threads: int,
    positions: list[str],
    timeout_s: int,
) -> list[OverlapRow]:
    """Run UCI with book positions and parse overlap lines."""
    engine = UCIEngine(exe, threads=threads)
    for idx, fen in enumerate(positions):
        engine.go_depth(fen, depth)
        print(f"  d={depth} t={threads} pos {idx + 1}/{len(positions)}", flush=True)
    collected = engine.quit(timeout_s=timeout_s)
    results: list[OverlapRow] = []
    for line in collected:
        parsed = parse_overlap_line(line)
        if parsed is not None and int(parsed.get("written", 0)) > 0:
            results.append(parsed)
    return results


def _build_csv_fieldnames() -> list[str]:
    """Build CSV header with all popcount columns."""
    base = [
        "depth",
        "nthreads",
        "ply",
        "total_entries",
        "written",
        "written_pct",
        "overlapped",
        "overlap_pct",
        "mean_pop",
        "elapsed_s",
    ]
    pops = [f"pop{k}" for k in range(MAX_POP + 1)]
    return base + pops


def main() -> (
    None
):  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
    """Entry point: parse arguments, run sweep, display and save results."""
    parser = argparse.ArgumentParser(
        description="Sweep contCorrHist thread overlap by depth and thread count",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--exe",
        default=DEFAULT_EXE,
        help=f"Path to instrumented binary (default: {DEFAULT_EXE})",
    )
    parser.add_argument(
        "--from",
        dest="from_depth",
        type=int,
        default=16,
        help="Starting depth (default: 16)",
    )
    parser.add_argument(
        "--to", type=int, default=22, help="Maximum depth (default: 22)"
    )
    parser.add_argument(
        "--depth",
        type=int,
        default=None,
        help="Single depth (overrides --from/--to)",
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
        "--book",
        type=str,
        default=None,
        help="EPD book file for UCI mode (omit for bench mode)",
    )
    parser.add_argument(
        "-n",
        "--num-positions",
        type=int,
        default=30,
        help="Positions to sample from book (default: 30)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for book sampling (default: 42)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_S,
        help=f"Per-run timeout in seconds (default: {DEFAULT_TIMEOUT_S})",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        help="Save summary table to .txt file",
    )
    parser.add_argument(
        "--csv",
        type=str,
        default=None,
        help="Save raw overlap data to CSV file",
    )
    args = parser.parse_args()

    thread_counts: list[int] = sorted(set(args.threads))

    if args.depth is not None:
        depths = [args.depth]
    else:
        depths = list(range(args.from_depth, args.to + 1))

    positions: list[str] | None = None
    if args.book:
        positions = load_book_positions(args.book, args.num_positions, args.seed)
        if not positions:
            print(f"No positions loaded from {args.book}", file=sys.stderr)
            sys.exit(1)
        print(f"Loaded {len(positions)} positions from {args.book}", flush=True)

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
        csvf = open(  # noqa: SIM115  # pylint: disable=consider-using-with
            args.csv,
            "w",
            newline="",
            encoding="utf-8",
        )
        csvw = csv.DictWriter(
            csvf, fieldnames=_build_csv_fieldnames(), extrasaction="ignore"
        )
        csvw.writeheader()
        csvf.flush()

    def emit(line: str) -> None:
        print(line, flush=True)
        if outf:
            outf.write(line + "\n")
            outf.flush()

    # Summary header: depth | 1T | 2T | 4T | ... | time
    # Cell = overlap% for ss-2 (primary metric)
    col_headers = " | ".join(f"{t:>6}T" for t in thread_counts)
    header = f"{'Depth':>5} | {col_headers} | {'Time':>8}"
    sep = "-" * len(header)

    mode = "book" if positions else "bench"
    emit(f"Mode: {mode}, depths: {depths[0]}-{depths[-1]}")
    emit("")
    emit(header)
    emit(sep)

    try:
        for depth in depths:
            row_t0 = time.time()
            overlap_by_threads: dict[int, float] = {}

            for threads in thread_counts:
                t0 = time.time()

                if positions:
                    results = run_book_overlap(
                        args.exe, depth, threads, positions, args.timeout
                    )
                else:
                    results = run_bench_overlap(args.exe, depth, threads, args.timeout)

                elapsed = time.time() - t0

                # Use ss-2 overlap% as the summary metric
                for row in results:
                    if int(row.get("ply", 0)) == 2:
                        overlap_by_threads[threads] = float(row["overlap_pct"])

                # Write all rows to CSV
                if csvw and csvf:
                    for row in results:
                        row["depth"] = depth
                        row["nthreads"] = threads
                        row["elapsed_s"] = round(elapsed, 1)
                        csvw.writerow(row)
                    csvf.flush()

            row_elapsed = time.time() - row_t0
            cells = " | ".join(
                (
                    f"{overlap_by_threads[t]:>5.1f}%"
                    if t in overlap_by_threads
                    else f"{'--':>6}"
                )
                for t in thread_counts
            )
            emit(f"{depth:>5} | {cells} | {row_elapsed:>7.1f}s")

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

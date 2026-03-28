#!/usr/bin/env python3
"""Run contcorr-occupancy instrumented Stockfish at each depth, summarize overlap.

Version 1.0
Copyright 2026 Maxim Masiutin.
License: GPL-3.0

Usage:
  python run_occupancy_sweep.py --exe bins/stockfish-instrument-contcorr-occupancy.exe
  python run_occupancy_sweep.py --from 13 --to 24 -t 16 -o results.txt --csv raw.csv
  python run_occupancy_sweep.py --book S:/books/UHO_Lichess_4852_v1.epd --seed 42

Outputs:
  Console/txt (-o): occupancy summary table per depth
  CSV (--csv): full popcount distribution per ply per depth
    Columns: depth,ply,total_entries,elapsed_s,pop0,pop1,...,pop32

The instrumented binary outputs lines like:
  overlap,2,1048576,pop0,pop1,...,pop32
where ply is 2 (ss-2) or 4 (ss-4), total_entries is PIECE_NB*SQ_NB*PIECE_NB*SQ_NB.
"""

import argparse
import csv
import os
import sys
import time
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shared.bench_runner import DEFAULT_EXE, pick_random_fen, run_bench  # noqa: E402
from shared.path_utils import validated_output_path  # noqa: E402

MAX_POP: int = 32
PLY_LABELS: list[int] = [2, 4]

RawRow = dict[str, Any]

BOOK_PATH: str = "S:/books/UHO_Lichess_4852_v1.epd"
BOOK_SEED: int = 739201


def parse_overlap_line(parts: list[str], depth: int) -> RawRow | None:
    """Parse an overlap CSV line. Returns row dict or None."""
    if len(parts) < 4 or parts[0] != "overlap":
        return None
    try:
        ply = int(parts[1])
        total = int(parts[2])
        pops = [int(x) for x in parts[3:]]
        if len(pops) < MAX_POP + 1:
            pops.extend([0] * (MAX_POP + 1 - len(pops)))
        row: RawRow = {"depth": depth, "ply": ply, "total_entries": total}
        for k in range(MAX_POP + 1):
            row[f"pop{k}"] = pops[k]
        return row
    except (ValueError, IndexError):
        return None


def run_depth(
    exe: str,
    depth: int,
    threads: int,
    hash_mb: int,
    fen: str | None,
) -> tuple[list[RawRow], float]:
    """Run bench at given depth, parse overlap lines, return rows and elapsed."""
    t0 = time.time()
    lines, rc = run_bench(exe, depth, threads, hash_mb, fen)
    elapsed = time.time() - t0

    if rc != 0:
        print(f"  depth {depth}: bench failed (rc={rc})", file=sys.stderr, flush=True)
        return [], elapsed

    rows: list[RawRow] = []
    seen_first_overlap = False
    for line in lines:
        parts = line.split(",")
        row = parse_overlap_line(parts, depth)
        if row is not None:
            if not seen_first_overlap:
                seen_first_overlap = True
            rows.append(row)
            if len(rows) == len(PLY_LABELS):
                break

    return rows, elapsed


def fmt_summary(row: RawRow, elapsed: float) -> str:
    """Format one summary line for a depth+ply."""
    total = row["total_entries"]
    vacant = row["pop0"]
    occupied = total - vacant
    occ_pct = 100.0 * occupied / total if total else 0.0
    all_threads_key = f"pop{MAX_POP}"
    all_threads = row.get(all_threads_key, 0)
    at_pct = 100.0 * all_threads / total if total else 0.0
    multi = sum(row.get(f"pop{k}", 0) for k in range(2, MAX_POP + 1))
    multi_pct = 100.0 * multi / total if total else 0.0
    return (
        f"{row['depth']:>5} | ss-{row['ply']:<2} | {total:>10,} | "
        f"{vacant:>10,} | {occupied:>10,} ({occ_pct:5.1f}%) | "
        f"{multi:>10,} ({multi_pct:5.1f}%) | "
        f"{all_threads:>8,} ({at_pct:5.1f}%) | {elapsed:>8.1f}s"
    )


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Sweep contcorr occupancy overlap by depth",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--exe", default=DEFAULT_EXE, help="Instrumented binary")
    parser.add_argument(
        "--from",
        dest="from_depth",
        type=int,
        default=13,
        help="Start depth (default: 13)",
    )
    parser.add_argument("--to", type=int, default=24, help="Max depth (default: 24)")
    parser.add_argument(
        "-t", "--threads", type=int, default=16, help="Thread count (default: 16)"
    )
    parser.add_argument("--hash", type=int, default=16, help="Hash MB (default: 16)")
    parser.add_argument(
        "-o", "--output", type=str, default=None, help="Save summary to .txt"
    )
    parser.add_argument("--csv", type=str, default=None, help="Save raw CSV")
    parser.add_argument(
        "--book",
        type=str,
        default=BOOK_PATH,
        help=f"EPD book path (default: {BOOK_PATH})",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=BOOK_SEED,
        help=f"Book position seed (default: {BOOK_SEED})",
    )
    parser.add_argument(
        "--no-book",
        action="store_true",
        help="Use default bench positions instead of book",
    )
    args = parser.parse_args()

    fen: str | None = None
    if not args.no_book:
        fen = pick_random_fen(args.book, args.seed)
        print(f"Book position (seed={args.seed}): {fen}", flush=True)

    header = (
        f"{'Depth':>5} | {'Ply':<5} | {'Total':>10} | "
        f"{'Vacant':>10} | {'Occupied':>18} | "
        f"{'Multi-thread':>18} | "
        f"{'All-threads':>16} | {'Time':>9}"
    )
    sep = "-" * len(header)

    outf = (
        open(validated_output_path(args.output), "w", newline="\n", encoding="utf-8")
        if args.output
        else None
    )
    csvf = None
    csvw: csv.DictWriter[str] | None = None
    if args.csv:
        csvf = open(validated_output_path(args.csv), "w", newline="", encoding="utf-8")
        fieldnames = ["depth", "ply", "total_entries", "elapsed_s"] + [
            f"pop{k}" for k in range(MAX_POP + 1)
        ]
        csvw = csv.DictWriter(csvf, fieldnames=fieldnames)
        csvw.writeheader()
        csvf.flush()

    def emit(line: str) -> None:
        print(line, flush=True)
        if outf:
            outf.write(line + "\n")
            outf.flush()

    try:
        if fen:
            emit(f"# FEN: {fen}")
            emit(f"# Seed: {args.seed}")
        emit(f"# Threads: {args.threads}, Hash: {args.hash} MB")
        emit("")
        emit(header)
        emit(sep)

        for depth in range(args.from_depth, args.to + 1):
            print(f"\n--- Running depth {depth} ...", flush=True)
            rows, elapsed = run_depth(args.exe, depth, args.threads, args.hash, fen)

            if not rows:
                emit(f"{depth:>5} | {'(no data)':^80}")
                continue

            for row in rows:
                row["elapsed_s"] = round(elapsed, 1)
                emit(fmt_summary(row, elapsed))

                if csvw and csvf:
                    csvw.writerow(row)
                    csvf.flush()
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

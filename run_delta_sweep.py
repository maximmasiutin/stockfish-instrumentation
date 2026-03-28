#!/usr/bin/env python3
"""Run instrumented Stockfish at each depth, summarize delta distributions.

Version 1.0
Copyright 2026 Maxim Masiutin.
License: GPL-3.0

Usage:
  python run_delta_sweep.py --from 1 --to 10
  python run_delta_sweep.py --exe ./stockfish --to 24 -o results.txt --csv raw.csv

Outputs:
  Console/txt (-o): zero-delta summary table per depth
  CSV (--csv): full delta distribution for every table at every depth
    Columns: depth,table,total_writes,elapsed_s,d0,d1,d2,...,d200p
"""

import argparse
import csv
import os
import re
import sys
import time
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shared.bench_runner import DEFAULT_EXE, DEFAULT_TIMEOUT_S, run_bench

TABLES = ["pawnCorr", "minorCorr", "nonpawnW", "nonpawnB", "contCorr2", "contCorr4"]
BIN_NAMES = [
    "d0",
    "d1",
    "d2",
    "d3",
    "d4_5",
    "d6_9",
    "d10_19",
    "d20_49",
    "d50_99",
    "d100_199",
    "d200p",
]

RawRow = dict[str, Any]
D0Dict = dict[str, float]


def _parse_csv_line(
    parts: list[str], depth: int
) -> tuple[str, int, list[float], RawRow] | None:
    """Parse a CSV output line. Returns (table, writes, bins, row) or None."""
    if len(parts) < 14:
        return None
    try:
        tbl = parts[1]
        if tbl not in TABLES:
            return None
        tw = int(parts[2])
        bins = [float(x) for x in parts[3:14]]
        row: RawRow = {"depth": depth, "table": tbl, "total_writes": tw}
        for i, name in enumerate(BIN_NAMES):
            row[name] = round(bins[i], 4)
        return tbl, tw, bins, row
    except (ValueError, IndexError):
        return None


def _parse_pretty_line(line: str, depth: int) -> tuple[str, int, float, RawRow] | None:
    """Parse a pretty-print output line. Returns (table, writes, d0, row) or None."""
    stripped = line.strip()
    for tbl in TABLES:
        if not stripped.startswith(tbl):
            continue
        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 13:
            return None
        pcts: list[float] = []
        for c in cells[2:13]:
            m = re.search(r"([\d.]+)%", c)
            pcts.append(float(m.group(1)) if m else 0.0)
        tw_val = 0
        m_tw = re.search(r"([\d.]+)M", cells[1])
        if m_tw:
            tw_val = int(float(m_tw.group(1)) * 1_000_000)
        else:
            m_raw = re.search(r"(\d+)", cells[1])
            if m_raw:
                tw_val = int(m_raw.group(1))
        row: RawRow = {"depth": depth, "table": tbl, "total_writes": tw_val}
        for i, name in enumerate(BIN_NAMES):
            row[name] = round(pcts[i], 4) if i < len(pcts) else 0.0
        return tbl, tw_val, pcts[0], row
    return None


def run_depth(  # pylint: disable=too-many-locals
    exe: str, depth: int, threads: int = 8, timeout_s: int = DEFAULT_TIMEOUT_S
) -> tuple[D0Dict, int, list[RawRow], bool]:
    """Run bench at given depth, return per-table raw rows, d0 summary, and timeout flag."""
    lines, timed_out = run_bench(exe, depth, threads, hash_mb=256, timeout_s=timeout_s)

    if timed_out:
        print(
            f"TIMEOUT after {timeout_s}s at depth {depth}", file=sys.stderr, flush=True
        )
        return {}, 0, [], True

    d0: D0Dict = {}
    total_writes = 0
    raw_rows: list[RawRow] = []
    found_csv = False

    for line in lines:
        parsed = _parse_csv_line(line.split(","), depth)
        if parsed is not None:
            tbl, tw, bins, row = parsed
            d0[tbl] = bins[0]
            total_writes += tw
            raw_rows.append(row)
            found_csv = True
            continue

        if found_csv:
            continue
        pretty = _parse_pretty_line(line, depth)
        if pretty is not None:
            tbl, tw_val, d0_pct, row = pretty
            d0[tbl] = d0_pct
            total_writes += tw_val
            raw_rows.append(row)

    return d0, total_writes, raw_rows, False


def fmt_row(
    depth: int, vals: list[float], mean: float, total_writes: int, elapsed: float
) -> str:
    """Format a summary table row."""
    return (
        f"{depth:>5} | {vals[0]:>9.1f}% | {vals[1]:>10.1f}% | {vals[2]:>9.1f}% | "
        f"{vals[3]:>9.1f}% | {vals[4]:>10.1f}% | {vals[5]:>10.1f}% | {mean:>5.1f}% | "
        f"{total_writes:>14,} | {elapsed:>8.1f}s"
    )


def main() -> None:  # pylint: disable=too-many-locals
    """Entry point: parse arguments, run sweep, display and save results."""
    parser = argparse.ArgumentParser(
        description="Sweep delta distributions by depth",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--exe",
        default=DEFAULT_EXE,
        help=f"Path to stockfish executable (default: {DEFAULT_EXE})",
    )
    parser.add_argument(
        "--from",
        dest="from_depth",
        type=int,
        default=1,
        help="Starting depth (default: 1)",
    )
    parser.add_argument("--to", type=int, default=8, help="Maximum depth (default: 8)")
    parser.add_argument(
        "-t", "--threads", type=int, default=8, help="Thread count (default: 8)"
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        help="Save summary table to .txt file (flushed per depth)",
    )
    parser.add_argument(
        "--csv",
        type=str,
        default=None,
        help="Save full raw delta distribution to CSV file",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_S,
        help=f"Per-depth timeout in seconds; stop sweep on timeout (default: {DEFAULT_TIMEOUT_S})",
    )
    args = parser.parse_args()

    header = (
        f"{'Depth':>5} | {'pawnCorr':>10} | {'minorCorr':>11} | {'nonpawnW':>10} | "
        f"{'nonpawnB':>10} | {'contCorr2':>11} | {'contCorr4':>11} | {'Mean':>6} | "
        f"{'TotalWrites':>14} | {'Time':>9}"
    )
    sep = "-" * len(header)

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
        fieldnames = ["depth", "table", "total_writes", "elapsed_s"] + BIN_NAMES
        csvw = csv.DictWriter(csvf, fieldnames=fieldnames)
        csvw.writeheader()
        csvf.flush()

    def emit(line: str) -> None:
        print(line, flush=True)
        if outf:
            outf.write(line + "\n")
            outf.flush()

    try:
        emit(header)
        emit(sep)

        for depth in range(args.from_depth, args.to + 1):
            t0 = time.time()
            d0, total_writes, raw_rows, did_timeout = run_depth(
                args.exe, depth, args.threads, timeout_s=args.timeout
            )
            elapsed = time.time() - t0
            print(f"\n--- depth {depth} ... done in {elapsed:.1f}s", flush=True)

            if did_timeout:
                emit(f"{depth:>5} | TIMEOUT after {args.timeout}s -- stopping sweep")
                break

            if not d0:
                row = f"{depth:>5} | {'(no data)':^80}"
            else:
                vals = [d0.get(t, 0.0) for t in TABLES]
                mean = sum(vals) / len(vals)
                row = fmt_row(depth, vals, mean, total_writes, elapsed)

            emit(row)

            if csvw and csvf and raw_rows:
                for r in raw_rows:
                    r["elapsed_s"] = round(elapsed, 1)
                    csvw.writerow(r)
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

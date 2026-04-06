#!/usr/bin/env python3
"""Run instrumented Stockfish to collect NMP (rootDepth, depth) pair distributions.

Runs multiple positions at each time control using 'go movetime', then
collects the NMP instrumentation CSV via the 'nmpstats' UCI command.

Usage:
  python run_nmp_rootdepth.py
  python run_nmp_rootdepth.py --exe S:/q/Stockfish/src/stockfish.exe
  python run_nmp_rootdepth.py --positions positions.epd --movetime 300,2000,6000
  python run_nmp_rootdepth.py -o scratchpad/nmp-rootdepth.csv

Output: CSV with columns: tc_ms,rootDepth,depth,count
"""

import argparse
import csv
import os
import subprocess
import sys
import time

DEFAULT_EXE = os.path.join("S:", os.sep, "q", "Stockfish", "src", "stockfish.exe")

DEFAULT_POSITIONS = [
    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
    "r1bqkbnr/pppppppp/2n5/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 1 2",
    "rnbqkb1r/pp2pppp/5n2/2ppP3/3P4/2N5/PPP2PPP/R1BQKBNR w KQkq d6 0 4",
    "r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/5N2/PPPP1PPP/RNBQ1RK1 w kq - 4 5",
    "r2q1rk1/ppp2ppp/2np1n2/2b1p1B1/2B1P1b1/2NP1N2/PPP2PPP/R2Q1RK1 w - - 6 8",
    "rnbq1rk1/ppp1bppp/4pn2/3p4/2PP4/2N2NP1/PP2PPBP/R1BQ1RK1 w - - 0 7",
    "r1b2rk1/2q1bppp/p2p1n2/np2p3/3PP3/1BN2N1P/PPB2PP1/R2QR1K1 w - - 0 13",
    "2rq1rk1/pb1nbppp/1p2pn2/3p4/2PP4/1PN1PNB1/P4PPP/R1BQ1RK1 w - - 0 11",
]

DEFAULT_MOVETIMES = [300, 2000, 6000]


def run_engine(
    exe: str,
    positions: list[str],
    movetime: int,
    threads: int,
    hash_mb: int,
) -> list[tuple[int, int, int]]:
    """Run engine on positions with given movetime, return (rootDepth, depth, count) tuples."""

    cmds: list[str] = [
        "uci",
        f"setoption name Threads value {threads}",
        f"setoption name Hash value {hash_mb}",
        "isready",
    ]

    for fen in positions:
        cmds.append("ucinewgame")
        cmds.append("isready")
        cmds.append(f"position fen {fen}")
        cmds.append(f"go movetime {movetime}")

    cmds.append("isready")
    cmds.append("nmpstats")
    cmds.append("quit")

    input_str = "\n".join(cmds) + "\n"

    proc = subprocess.run(
        [exe],
        input=input_str,
        capture_output=True,
        text=True,
        timeout=max(60, len(positions) * movetime // 1000 * 3 + 30),
    )

    results: list[tuple[int, int, int]] = []
    in_csv = False
    for line in proc.stderr.splitlines():
        line = line.strip()
        if line == "NMP_ROOTDEPTH_DEPTH_CSV_BEGIN":
            in_csv = True
            continue
        if line == "NMP_ROOTDEPTH_DEPTH_CSV_END":
            in_csv = False
            continue
        if in_csv and line and not line.startswith("rootDepth,"):
            parts = line.split(",")
            if len(parts) == 3:
                results.append((int(parts[0]), int(parts[1]), int(parts[2])))

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="NMP rootDepth instrumentation")
    parser.add_argument("--exe", default=DEFAULT_EXE, help="Path to instrumented binary")
    parser.add_argument(
        "--movetime",
        default=",".join(str(t) for t in DEFAULT_MOVETIMES),
        help="Comma-separated movetimes in ms (default: 300,2000,6000)",
    )
    parser.add_argument("--threads", type=int, default=1, help="Thread count")
    parser.add_argument("--hash", type=int, default=256, help="Hash in MB")
    parser.add_argument("--positions", help="EPD file with positions (one FEN per line)")
    parser.add_argument("-o", "--output", help="Output CSV file path")
    args = parser.parse_args()

    movetimes = [int(x) for x in args.movetime.split(",")]

    positions = DEFAULT_POSITIONS
    if args.positions:
        with open(args.positions) as f:
            positions = [line.strip() for line in f if line.strip()]

    all_rows: list[dict[str, int]] = []

    for mt in movetimes:
        print(f"Running {len(positions)} positions at movetime={mt}ms, "
              f"threads={args.threads}, hash={args.hash}MB...")
        t0 = time.time()
        results = run_engine(args.exe, positions, mt, args.threads, args.hash)
        elapsed = time.time() - t0
        total = sum(c for _, _, c in results)
        print(f"  {elapsed:.1f}s elapsed, {len(results)} cells, {total:,} NMP entries")

        for rd, d, c in results:
            all_rows.append({"tc_ms": mt, "rootDepth": rd, "depth": d, "count": c})

    if args.output:
        with open(args.output, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["tc_ms", "rootDepth", "depth", "count"])
            writer.writeheader()
            writer.writerows(all_rows)
        print(f"Written {len(all_rows)} rows to {args.output}")
    else:
        print("\ntc_ms,rootDepth,depth,count")
        for row in all_rows:
            print(f"{row['tc_ms']},{row['rootDepth']},{row['depth']},{row['count']}")

    for mt in movetimes:
        tc_rows = [r for r in all_rows if r["tc_ms"] == mt]
        total = sum(r["count"] for r in tc_rows)
        if total == 0:
            continue
        print(f"\n=== movetime={mt}ms ({total:,} NMP entries) ===")
        print(f"{'rootDepth':>10} {'depth':>6} {'count':>12} {'pct':>7}")
        sorted_rows = sorted(tc_rows, key=lambda r: -r["count"])
        for r in sorted_rows[:30]:
            pct = 100.0 * r["count"] / total
            print(f"{r['rootDepth']:>10} {r['depth']:>6} {r['count']:>12,} {pct:>6.2f}%")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Run instrumented Stockfish to collect NMP rootDepth-only distributions.

Runs multiple positions at each time control using 'go movetime', then
collects the NMP rootDepth instrumentation CSV via the 'nmpstats' UCI command.

Unlike run_nmp_rootdepth.py which collects (rootDepth, depth) pairs, this
script collects rootDepth marginal distribution only, with count and percentage.

Usage:
  python run_nmp_rootdepth_only.py
  python run_nmp_rootdepth_only.py --exe S:/q/Stockfish/src/stockfish.exe
  python run_nmp_rootdepth_only.py --movetime 300,2000,6000,12000,24000
  python run_nmp_rootdepth_only.py -o scratchpad/nmp-rootdepth-only.csv

Output: CSV with columns: tc_ms,rootDepth,count,pct
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

DEFAULT_MOVETIMES = [300, 2000, 6000, 12000, 24000]


def _build_commands(
    positions: list[str], movetime: int, threads: int, hash_mb: int
) -> list[str]:
    """Build UCI command sequence for rootDepth instrumentation."""
    cmds: list[str] = [
        "uci",
        f"setoption name Threads value {threads}",
        f"setoption name Hash value {hash_mb}",
        "isready",
        "nmpreset",
    ]
    for fen in positions:
        cmds.append("ucinewgame")
        cmds.append("isready")
        cmds.append(f"position fen {fen}")
        cmds.append(f"go movetime {movetime}")
    wait_s = len(positions) * movetime / 1000 + 10
    cmds.append(f"wait {int(wait_s)}")
    cmds.append("isready")
    cmds.append("nmpstats")
    cmds.append("quit")
    return cmds


def _parse_csv(stderr: str) -> list[tuple[int, int, float]]:
    """Parse NMP rootDepth CSV from engine stderr."""
    results: list[tuple[int, int, float]] = []
    in_csv = False
    for line in stderr.splitlines():
        line = line.strip()
        if line == "NMP_ROOTDEPTH_CSV_BEGIN":
            in_csv = True
            continue
        if line == "NMP_ROOTDEPTH_CSV_END":
            in_csv = False
            continue
        if in_csv and line and not line.startswith("rootDepth,"):
            parts = line.split(",")
            if len(parts) == 3:
                results.append((int(parts[0]), int(parts[1]), float(parts[2])))
    return results


def run_engine(
    exe: str,
    positions: list[str],
    movetime: int,
    threads: int,
    hash_mb: int,
) -> list[tuple[int, int, float]]:
    """Run engine on positions, return (rootDepth, count, pct) tuples."""

    cmds = _build_commands(positions, movetime, threads, hash_mb)
    input_str = "\n".join(cmds) + "\n"
    timeout_s = max(120, int(len(positions) * movetime / 1000 * 3 + 60))

    with subprocess.Popen(
        [exe],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as proc:
        assert proc.stdin is not None
        proc.stdin.write(input_str)
        proc.stdin.flush()

        try:
            _, stderr = proc.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            proc.kill()
            _, stderr = proc.communicate()
            print(f"WARNING: Engine timed out after {timeout_s}s", file=sys.stderr)

    return _parse_csv(stderr)


def _print_summary(
    all_rows: list[dict[str, float | int]], movetimes: list[int]
) -> None:
    """Print per-TC summary tables."""
    for mt in movetimes:
        tc_rows = [r for r in all_rows if r["tc_ms"] == mt]
        total = sum(int(r["count"]) for r in tc_rows)
        if total == 0:
            continue
        print(f"\n=== movetime={mt}ms ({total:,} NMP entries) ===")
        print(f"{'rootDepth':>10} {'count':>12} {'pct':>7}")
        sorted_rows = sorted(tc_rows, key=lambda r: int(r["rootDepth"]))
        for r in sorted_rows:
            print(
                f"{int(r['rootDepth']):>10} {int(r['count']):>12,} {float(r['pct']):>6.2f}%"
            )


def _write_output(all_rows: list[dict[str, float | int]], output: str | None) -> None:
    """Write CSV output or print to stdout."""
    if output:
        with open(output, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, fieldnames=["tc_ms", "rootDepth", "count", "pct"]
            )
            writer.writeheader()
            writer.writerows(all_rows)
        print(f"Written {len(all_rows)} rows to {output}")
    else:
        print("\ntc_ms,rootDepth,count,pct")
        for row in all_rows:
            print(f"{row['tc_ms']},{row['rootDepth']},{row['count']},{row['pct']}")


def main() -> None:
    """Entry point for NMP rootDepth-only distribution instrumentation."""
    parser = argparse.ArgumentParser(
        description="NMP rootDepth-only distribution instrumentation"
    )
    parser.add_argument(
        "--exe", default=DEFAULT_EXE, help="Path to instrumented binary"
    )
    parser.add_argument(
        "--movetime",
        default=",".join(str(t) for t in DEFAULT_MOVETIMES),
        help="Comma-separated movetimes in ms (default: 300,2000,6000,12000,24000)",
    )
    parser.add_argument("--threads", type=int, default=1, help="Thread count")
    parser.add_argument("--hash", type=int, default=256, help="Hash in MB")
    parser.add_argument(
        "--positions", help="EPD file with positions (one FEN per line)"
    )
    parser.add_argument("-o", "--output", help="Output CSV file path")
    args = parser.parse_args()

    movetimes = [int(x) for x in args.movetime.split(",")]

    positions = DEFAULT_POSITIONS
    if args.positions:
        with open(args.positions, encoding="utf-8") as f:
            positions = [line.strip() for line in f if line.strip()]

    all_rows: list[dict[str, float | int]] = []

    for mt in movetimes:
        print(
            f"Running {len(positions)} positions at movetime={mt}ms, "
            f"threads={args.threads}, hash={args.hash}MB..."
        )
        t0 = time.time()
        results = run_engine(args.exe, positions, mt, args.threads, args.hash)
        elapsed = time.time() - t0
        total = sum(c for _, c, _ in results)
        print(
            f"  {elapsed:.1f}s elapsed, {len(results)} rootDepth values, {total:,} NMP entries"
        )

        for rd, c, pct in results:
            all_rows.append(
                {"tc_ms": mt, "rootDepth": rd, "count": c, "pct": round(pct, 6)}
            )

    _write_output(all_rows, args.output)
    _print_summary(all_rows, movetimes)


if __name__ == "__main__":
    main()

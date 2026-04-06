"""Measure search depth at SMP time controls.

Uses the same methodology as nmp-mrd instrumentation: same 3 UHO positions
(seed=1), one exe per position, proper movetimes (65 moves/game).
No instrumented binary needed; parses standard UCI info depth output.

Usage:
    python measure_depth_smp.py <binary> [--hash N] [--threads N]
"""

import argparse
import random
import re
import sys

from shared.path_utils import validated_input_path
from shared.uci_engine import UCIEngine

BOOK_PATH = r"C:\books\UHO_Lichess_4852_v1.epd"
SEED = 1
COUNT = 3
MOVES_PER_GAME = 65

# SMP TCs from Fishtest
SMP_TCS: list[tuple[str, int, int]] = [
    # (label, base_ms, inc_ms)
    ("STC SMP 5+0.05", 5000, 50),
    ("LTC SMP 20+0.2", 20000, 200),
]

# 1T TCs for comparison
SINGLE_TCS: list[tuple[str, int, int]] = [
    ("STC 1T 10+0.1", 10000, 100),
    ("LTC 1T 60+0.6", 60000, 600),
]


def compute_movetime(base_ms: int, inc_ms: int) -> int:
    """Compute per-move time from TC using 65 moves/game."""
    return base_ms // MOVES_PER_GAME + inc_ms


def extract_final_depth(lines: list[str]) -> tuple[int, int]:
    """Extract the last info depth and seldepth before bestmove."""
    last_depth = 0
    last_seldepth = 0
    for line in lines:
        m = re.match(r"info depth (\d+) seldepth (\d+)", line)
        if m:
            last_depth = int(m.group(1))
            last_seldepth = int(m.group(2))
    return last_depth, last_seldepth


def run_one_position(
    binary: str, fen: str, movetime_ms: int, threads: int, hash_mb: int
) -> tuple[int, int]:
    """Run one position and return (depth, seldepth)."""
    engine = UCIEngine(exe=binary, threads=threads, hash_mb=hash_mb)
    engine.go_movetime(fen, movetime_ms)
    lines = engine.quit()
    return extract_final_depth(lines)


def load_positions() -> list[str]:
    """Load 3 UHO positions with seed=1 (same as nmp-mrd instrumentation)."""
    epd_path = validated_input_path(BOOK_PATH)
    all_fens = [
        line.strip()
        for line in epd_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for i, fen in enumerate(all_fens):
        if ";" in fen:
            all_fens[i] = fen[: fen.index(";")].strip()
    rng = random.Random(SEED)
    return rng.sample(all_fens, min(COUNT, len(all_fens)))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure search depth at SMP time controls"
    )
    parser.add_argument("binary", help="Path to Stockfish binary")
    parser.add_argument(
        "--hash", type=int, default=128, help="Hash size in MB (default: 128)"
    )
    parser.add_argument(
        "--threads", type=int, default=8, help="Thread count (default: 8)"
    )
    parser.add_argument(
        "--include-1t",
        action="store_true",
        help="Also measure 1T TCs for comparison",
    )
    args = parser.parse_args()

    fens = load_positions()

    print(
        f"Positions: {len(fens)} from UHO_Lichess_4852_v1.epd (seed={SEED})",
        file=sys.stderr,
    )
    for i, fen in enumerate(fens):
        print(f"  [{i}] {fen}", file=sys.stderr)

    tcs = list(SMP_TCS)
    if args.include_1t:
        tcs.extend(SINGLE_TCS)

    for label, base_ms, inc_ms in tcs:
        movetime = compute_movetime(base_ms, inc_ms)
        threads = args.threads if "SMP" in label else 1

        print(f"\n=== {label} (movetime={movetime}ms, {threads}T) ===", file=sys.stderr)
        print(f"\n{label} | movetime={movetime}ms | {threads}T | hash={args.hash}MB")
        print(f"{'Position':>4} | {'Depth':>5} | {'SelDepth':>8} | FEN")
        print(f"{'----':>4} | {'-----':>5} | {'--------':>8} | ---")

        depths: list[int] = []
        seldepths: list[int] = []

        for idx, fen in enumerate(fens):
            print(
                f"  Running position {idx + 1}/{len(fens)}...",
                file=sys.stderr,
                flush=True,
            )
            depth, seldepth = run_one_position(
                args.binary, fen, movetime, threads, args.hash
            )
            depths.append(depth)
            seldepths.append(seldepth)
            print(f"{idx:>4} | {depth:>5} | {seldepth:>8} | {fen[:60]}")

        print(
            f"  Summary: depth min={min(depths)} max={max(depths)} "
            f"median={sorted(depths)[len(depths)//2]}",
        )


if __name__ == "__main__":
    main()

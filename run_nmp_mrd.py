"""Run NMP MRD instrumentation on book positions.

Measures how often the maxRootDepth condition fires in NMP at each depth.
Each position runs as a separate exe invocation to avoid counter accumulation
issues and ensure per-position isolation of maxRootDepth.

Uses shared.uci_engine.UCIEngine with go_movetime for realistic TC simulation.

Usage:
    python run_nmp_mrd.py <binary> <epd_file> <output_csv>
        [--movetime MS] [--count N] [--hash N] [--seed N]

Example:
    python run_nmp_mrd.py stockfish.exe book.epd stc.csv --movetime 10000 --count 3
    python run_nmp_mrd.py stockfish.exe book.epd ltc.csv --movetime 80000 --count 3
"""

import argparse
import random
import sys

from shared.path_utils import validated_input_path, validated_output_path
from shared.uci_engine import UCIEngine


def parse_mrd_csv(lines: list[str]) -> list[dict[str, str]]:
    """Extract NMP_MRD CSV rows from engine output."""
    inside = False
    header: list[str] = []
    rows: list[dict[str, str]] = []
    for line in lines:
        stripped = line.strip()
        if stripped == "NMP_MRD_CSV_START":
            inside = True
            continue
        if stripped == "NMP_MRD_CSV_END":
            break
        if inside and stripped:
            parts = stripped.split(",")
            if parts[0] == "depth":
                header = parts
            else:
                rows.append(dict(zip(header, parts)))
    return rows


def run_one_position(
    binary: str, fen: str, movetime_ms: int, hash_mb: int, threads: int = 1
) -> list[dict[str, str]]:
    """Run one position and return parsed MRD rows."""
    engine = UCIEngine(exe=binary, threads=threads, hash_mb=hash_mb)
    engine.go_movetime(fen, movetime_ms)
    lines = engine.quit()
    return parse_mrd_csv(lines)


def merge_rows(
    accumulated: dict[int, dict[str, int]], rows: list[dict[str, str]]
) -> None:
    """Merge per-position rows into accumulated totals."""
    for row in rows:
        d = int(row["depth"])
        if d not in accumulated:
            accumulated[d] = {"nmpTotal": 0, "mrdFired": 0, "rSum": 0}
        accumulated[d]["nmpTotal"] += int(row["nmpTotal"])
        accumulated[d]["mrdFired"] += int(row["mrdFired"])
        # avgR * nmpTotal gives rSum
        avg_r = float(row["avgR"])
        n = int(row["nmpTotal"])
        accumulated[d]["rSum"] += round(avg_r * n)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run NMP MRD instrumentation on book positions"
    )
    parser.add_argument("binary", help="Path to instrumented binary")
    parser.add_argument("epd_file", help="EPD file with positions")
    parser.add_argument("output_csv", help="Output CSV file")
    parser.add_argument(
        "--movetime",
        type=int,
        default=10000,
        help="Movetime in ms per position (default: 10000 for STC)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=3,
        help="Number of positions to test (default: 3)",
    )
    parser.add_argument(
        "--hash", type=int, default=16, help="Hash size in MB (default: 16)"
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=1,
        choices=range(1, 1025),
        metavar="N",
        help="Thread count, 1-1024 (default: 1)",
    )
    parser.add_argument(
        "--seed", type=int, default=1, help="Random seed for position selection"
    )
    args = parser.parse_args()

    epd_path = validated_input_path(args.epd_file)
    out_path = validated_output_path(args.output_csv)

    all_fens = [
        line.strip()
        for line in epd_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for i, fen in enumerate(all_fens):
        if ";" in fen:
            all_fens[i] = fen[: fen.index(";")].strip()

    rng = random.Random(args.seed)
    fens = rng.sample(all_fens, min(args.count, len(all_fens)))

    print(
        f"Running {len(fens)} positions, movetime={args.movetime}ms, "
        f"threads={args.threads}, hash={args.hash}MB, seed={args.seed}",
        file=sys.stderr,
    )
    for i, fen in enumerate(fens):
        print(f"  [{i}] {fen}", file=sys.stderr)

    accumulated: dict[int, dict[str, int]] = {}

    for idx, fen in enumerate(fens):
        print(
            f"\nPosition {idx + 1}/{len(fens)}: {fen[:70]}",
            file=sys.stderr,
            flush=True,
        )
        rows = run_one_position(
            args.binary, fen, args.movetime, args.hash, args.threads
        )
        print(f"  Got {len(rows)} depth rows", file=sys.stderr, flush=True)
        merge_rows(accumulated, rows)

    with open(out_path, "w", encoding="utf-8") as out:
        out.write("depth,nmpTotal,mrdFired,mrdPct,avgR\n")
        for d in sorted(accumulated):
            total = accumulated[d]["nmpTotal"]
            fired = accumulated[d]["mrdFired"]
            r_sum = accumulated[d]["rSum"]
            pct = 100.0 * fired / total if total > 0 else 0
            avg_r = r_sum / total if total > 0 else 0
            out.write(f"{d},{total},{fired},{pct:.4f},{avg_r:.4f}\n")

    print(f"\nOutput written to {args.output_csv}", file=sys.stderr)
    print(f"Positions: {len(fens)}, movetime: {args.movetime}ms", file=sys.stderr)

    grand_total = sum(v["nmpTotal"] for v in accumulated.values())
    grand_fired = sum(v["mrdFired"] for v in accumulated.values())
    pct = 100.0 * grand_fired / grand_total if grand_total > 0 else 0
    print(
        f"Total NMP entries: {grand_total}, MRD fired: {grand_fired} ({pct:.1f}%)",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()

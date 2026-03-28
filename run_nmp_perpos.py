"""Run NMP v2 instrumentation per-position with per-depth output.

CRITICAL: Runs ONE position per stockfish invocation to avoid counter
accumulation across positions. Using bench with multiple positions gives
blended rates that do not reflect any single position's behavior.

Positions must be saved in an EPD file for reproducibility. Always record
which positions were used and how many NMP entries each produced.

Uses shared.bench_runner.run_bench() for execution.

Usage:
    python run_nmp_perpos.py <binary> <epd_file> <output_csv> [--depth N] [--hash N]

Example:
    python run_nmp_perpos.py path/to/instrument-nmp-v2.exe positions.epd output.csv --depth 26
"""

import argparse
import sys
from pathlib import Path

from shared.bench_runner import run_bench


def run_single_position(
    binary: str,
    fen: str,
    depth: int,
    hash_mb: int,
) -> list[str]:
    """Run bench on ONE FEN and return raw nmp_cv CSV lines."""
    lines, _ = run_bench(
        exe=binary,
        depth=depth,
        threads=1,
        hash_mb=hash_mb,
        fen=fen,
        timeout_s=600,
    )
    csv_lines: list[str] = []
    for line in lines:
        if line.startswith("nmp_cv,") or line.startswith("nmp_signal,"):
            csv_lines.append(line)
    return csv_lines


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run NMP v2 instrumentation per position (one exe run per position)"
    )
    parser.add_argument("binary", help="Path to instrumented v2 binary")
    parser.add_argument("epd_file", help="EPD file with positions (one FEN per line)")
    parser.add_argument("output_csv", help="Output CSV file")
    parser.add_argument(
        "--depth", type=int, default=26, help="Search depth (default: 26)"
    )
    parser.add_argument(
        "--hash", type=int, default=16, help="Hash size in MB (default: 16)"
    )
    args = parser.parse_args()

    fens = [
        line.strip()
        for line in Path(args.epd_file).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    print(
        f"Processing {len(fens)} positions at depth {args.depth} "
        f"(one exe run per position)...",
        file=sys.stderr,
    )

    header_written = False
    with open(args.output_csv, "w", encoding="utf-8") as out:
        for idx, fen in enumerate(fens):
            print(
                f"  Position {idx + 1}/{len(fens)}: {fen[:60]}...",
                file=sys.stderr,
            )
            csv_lines = run_single_position(args.binary, fen, args.depth, args.hash)

            data_count = 0
            for line in csv_lines:
                parts = line.split(",")
                if parts[1] == "depth":
                    if not header_written:
                        out.write(f"pos_idx,fen,{line}\n")
                        header_written = True
                    continue
                out.write(f"{idx},{fen},{line}\n")
                data_count += 1

            print(
                f"    Got {data_count} depth rows",
                file=sys.stderr,
            )

    print(f"Output written to {args.output_csv}", file=sys.stderr)
    print(f"Positions file: {args.epd_file}", file=sys.stderr)
    print(
        f"IMPORTANT: Keep {args.epd_file} for reproducibility",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()

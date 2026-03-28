"""Compute NMP correction value frequency table from v2 instrument data.

Reads the 32cp-bin instrument CSV and produces cumulative positive tail
activation rates at thresholds 128, 192, 256, 288, 320, 384cp per depth.
Also computes the (steps * depth) / 16 R-adjustment for the graduated formula.

Usage:
    python compute_nmp_freq_table.py scratchpad/nmp-v2-1t-d20.csv
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shared.path_utils import validated_input_path  # noqa: E402


# Column names for bins (32cp each from <-512 to >=544)
# The positive bins of interest:
# cp128 = [128,160), cp160 = [160,192), cp192 = [192,224), ...
# cv > 128cp = sum of cp128 through ge544
# cv > 192cp = sum of cp192 through ge544
# cv > 256cp = sum of cp256 through ge544
# cv > 288cp = sum of cp288 through ge544

POSITIVE_BIN_NAMES = [
    "cp128",
    "cp160",
    "cp192",
    "cp224",
    "cp256",
    "cp288",
    "cp320",
    "cp352",
    "cp384",
    "cp416",
    "cp448",
    "cp480",
    "cp512",
    "ge544",
]

NEGATIVE_BIN_NAMES = [
    "lt-512",
    "cp-480",
    "cp-448",
    "cp-416",
    "cp-384",
    "cp-352",
    "cp-320",
    "cp-288",
    "cp-256",
    "cp-224",
    "cp-192",
    "cp-160",
    "cp-128",
]


def cumulative_tail(row: dict[str, str], start_bin: str) -> int:
    """Sum all bins from start_bin to the end (ge544)."""
    try:
        idx = POSITIVE_BIN_NAMES.index(start_bin)
        return sum(int(row.get(n, "0")) for n in POSITIVE_BIN_NAMES[idx:])
    except ValueError:
        return 0


def neg_cumulative_tail(row: dict[str, str], start_bin: str) -> int:
    """Sum all bins from lt-512 to start_bin (inclusive)."""
    total = 0
    for name in NEGATIVE_BIN_NAMES:
        total += int(row.get(name, "0"))
        if name == start_bin:
            break
    return total


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python compute_nmp_freq_table.py <csv>", file=sys.stderr)
        sys.exit(1)

    lines = validated_input_path(sys.argv[1]).read_text(encoding="utf-8").splitlines()

    # Parse header and data
    header_line = lines[0]
    header = header_line.split(",")

    rows: list[dict[str, str]] = []
    for line in lines[1:]:
        if not line.startswith("nmp_cv,"):
            continue
        parts = line.split(",")
        row = dict(zip(header, parts, strict=False))
        rows.append(row)

    # Print header
    print(
        f"{'Depth':>5s} {'Entered':>8s} "
        f"{'cv>128':>7s} {'cv>192':>7s} {'cv>256':>7s} {'cv>288':>7s} "
        f"{'cv>320':>7s} {'cv>384':>7s} "
        f"{'cv<-192':>7s} {'cv<-288':>7s} "
        f"{'Impr%':>6s}"
    )
    print(
        f"{'':>5s} {'':>8s} "
        f"{'%':>7s} {'%':>7s} {'%':>7s} {'%':>7s} "
        f"{'%':>7s} {'%':>7s} "
        f"{'%':>7s} {'%':>7s} "
        f"{'':>6s}"
    )
    print("-" * 100)

    for row in rows:
        depth = int(row["depth"])
        entered = int(row["entered"])
        if entered == 0:
            continue

        cv128 = cumulative_tail(row, "cp128")
        cv192 = cumulative_tail(row, "cp192")
        cv256 = cumulative_tail(row, "cp256")
        cv288 = cumulative_tail(row, "cp288")
        cv320 = cumulative_tail(row, "cp320")
        cv384 = cumulative_tail(row, "cp384")

        neg192 = neg_cumulative_tail(row, "cp-192")
        neg288 = neg_cumulative_tail(row, "cp-288")

        impr_pct = row.get("impr_pct", "0")

        print(
            f"{depth:>5d} {entered:>8d} "
            f"{100*cv128/entered:>7.2f} {100*cv192/entered:>7.2f} "
            f"{100*cv256/entered:>7.2f} {100*cv288/entered:>7.2f} "
            f"{100*cv320/entered:>7.2f} {100*cv384/entered:>7.2f} "
            f"{100*neg192/entered:>7.2f} {100*neg288/entered:>7.2f} "
            f"{float(impr_pct):>6.1f}"
        )

    # Now print the R-adjustment table for (steps * depth) / 16
    # with thresholds 192/256/288
    print()
    print("R-adjustment table: ((cv>192)+(cv>256)+(cv>288)) * depth / 16")
    print("=" * 90)
    print(
        f"{'Depth':>5s} {'steps=1':>8s} {'steps=2':>8s} {'steps=3':>8s} "
        f"{'s1 rate':>8s} {'s2 rate':>8s} {'s3 rate':>8s} "
        f"{'Eff R':>7s}"
    )
    print(
        f"{'':>5s} {'[192,256)':>8s} {'[256,288)':>8s} {'>=288':>8s} "
        f"{'%':>8s} {'%':>8s} {'%':>8s} "
        f"{'':>7s}"
    )
    print("-" * 90)

    for row in rows:
        if row["depth"] == "depth":
            continue
        depth = int(row["depth"])
        entered = int(row["entered"])
        if entered == 0 or depth > 32:
            continue

        cv192 = cumulative_tail(row, "cp192")
        cv256 = cumulative_tail(row, "cp256")
        cv288 = cumulative_tail(row, "cp288")

        # Band rates
        band1 = cv192 - cv256  # [192, 256)
        band2 = cv256 - cv288  # [256, 288)
        band3 = cv288  # >= 288

        r1 = (1 * depth) // 16
        r2 = (2 * depth) // 16
        r3 = (3 * depth) // 16

        rate1 = 100 * band1 / entered if entered else 0
        rate2 = 100 * band2 / entered if entered else 0
        rate3 = 100 * band3 / entered if entered else 0

        eff_r = (rate1 * r1 + rate2 * r2 + rate3 * r3) / 100

        print(
            f"{depth:>5d} {r1:>8d} {r2:>8d} {r3:>8d} "
            f"{rate1:>8.2f} {rate2:>8.2f} {rate3:>8.2f} "
            f"{eff_r:>7.3f}"
        )


if __name__ == "__main__":
    main()

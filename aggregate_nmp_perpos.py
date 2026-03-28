"""Aggregate per-position NMP v2 data into per-depth totals.

Reads the per-position CSV from run_nmp_v2_per_position.py and sums
all bin counts across positions for each depth. Outputs the standard
v2 format that compute_nmp_freq_table.py expects.

Also shows per-position summaries and the positions used.

Usage:
    python aggregate_nmp_perpos.py scratchpad/nmp-v2-perpos-d26.csv > scratchpad/nmp-v2-agg-d26.csv
    python aggregate_nmp_perpos.py scratchpad/nmp-v2-perpos-d26.csv --summary
"""

import sys
from collections import defaultdict
from pathlib import Path

BIN_COLS = [
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
    "cp-96",
    "cp-64",
    "cp-32",
    "cp0",
    "cp32",
    "cp64",
    "cp96",
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


def main() -> None:
    if len(sys.argv) < 2:
        print(
            "Usage: python aggregate_nmp_perpos.py <csv> [--summary]",
            file=sys.stderr,
        )
        sys.exit(1)

    csv_path = sys.argv[1]
    show_summary = "--summary" in sys.argv

    lines = Path(csv_path).read_text(encoding="utf-8").splitlines()
    header = lines[0].split(",")

    depth_totals: dict[int, dict[str, int]] = defaultdict(
        lambda: {"entered": 0, "improving": 0}
    )

    positions: dict[int, str] = {}
    pos_entered: dict[int, int] = defaultdict(int)

    for line in lines[1:]:
        parts = line.split(",")
        row = dict(zip(header, parts, strict=False))

        pos_idx = int(row["pos_idx"])
        fen = row["fen"]
        depth = int(row["depth"])
        entered = int(row["entered"])
        improving = int(row["improving"])

        positions[pos_idx] = fen
        pos_entered[pos_idx] += entered

        dt = depth_totals[depth]
        dt["entered"] += entered
        dt["improving"] += improving
        for col in BIN_COLS:
            dt[col] = dt.get(col, 0) + int(row.get(col, "0"))

    if show_summary:
        print("=== Positions used ===", file=sys.stderr)
        for idx in sorted(positions):
            print(
                f"  [{idx}] {positions[idx][:80]}  "
                f"(NMP entered: {pos_entered[idx]})",
                file=sys.stderr,
            )
        print(f"\nTotal positions: {len(positions)}", file=sys.stderr)
        total_nmp = sum(pos_entered.values())
        print(f"Total NMP entries: {total_nmp}", file=sys.stderr)
        print(file=sys.stderr)

    out_header = "nmp_cv,depth,entered,improving,impr_pct," + ",".join(BIN_COLS)
    print(out_header)

    for depth in sorted(depth_totals):
        dt = depth_totals[depth]
        entered = dt["entered"]
        improving = dt["improving"]
        impr_pct = f"{100 * improving / entered:.1f}" if entered else "0"
        bins_str = ",".join(str(dt.get(col, 0)) for col in BIN_COLS)
        print(f"nmp_cv,{depth},{entered},{improving},{impr_pct},{bins_str}")


if __name__ == "__main__":
    main()

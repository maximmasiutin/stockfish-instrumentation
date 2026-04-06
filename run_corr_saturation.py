"""Run correction saturation instrumentation at multiple TCs.

Uses ucinewgame between positions so each search starts with fresh
maxRootDepth. Records entry value distribution and maxRootDepth histogram
at correction write sites.

Methodology: same 3 UHO positions (seed=1), movetime = base/65 + inc,
PGO binary, configurable threads and hash.

Usage:
    python run_corr_saturation.py <binary> [options]

Examples:
    python run_corr_saturation.py stockfish.exe --tc 10+0.1 --threads 1
    python run_corr_saturation.py stockfish.exe --tc 5+0.05 --threads 8
    python run_corr_saturation.py stockfish.exe --tc 5+0.05 10+0.1 20+0.2 80+0.8 --threads 8
"""

import argparse
import random
import subprocess
import sys
import threading

from shared.path_utils import validated_input_path

BOOK_PATH = r"C:\books\UHO_Lichess_4852_v1.epd"
SEED = 1
COUNT = 3
MOVES_PER_GAME = 65


def parse_tc(tc_str: str) -> tuple[int, int]:
    """Parse TC string like '5+0.05' into (base_ms, inc_ms)."""
    parts = tc_str.split("+")
    base_s = float(parts[0])
    inc_s = float(parts[1]) if len(parts) > 1 else 0.0
    return int(base_s * 1000), int(inc_s * 1000)


def compute_movetime(base_ms: int, inc_ms: int) -> int:
    """Compute per-move time from TC using 65 moves/game."""
    return base_ms // MOVES_PER_GAME + inc_ms


def load_positions() -> list[str]:
    """Load 3 UHO positions with seed=1."""
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


class SimpleEngine:
    """Minimal UCI engine wrapper with ucinewgame support."""

    def __init__(self, exe: str, threads: int, hash_mb: int) -> None:
        self.proc = subprocess.Popen(
            [exe],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        if self.proc.stdin is None or self.proc.stdout is None:
            raise RuntimeError("Failed to open stdin/stdout pipes")
        self._stdin = self.proc.stdin
        self._stdout = self.proc.stdout
        self._all_lines: list[str] = []
        self._send("uci")
        self._wait_for("uciok")
        self._send(f"setoption name Threads value {threads}")
        self._send(f"setoption name Hash value {hash_mb}")
        self._send("isready")
        self._wait_for("readyok")

    def _send(self, cmd: str) -> None:
        self._stdin.write(cmd + "\n")
        self._stdin.flush()

    def _wait_for(self, token: str) -> list[str]:
        lines: list[str] = []
        while True:
            line = self._stdout.readline()
            if not line:
                raise RuntimeError(f"EOF before '{token}'")
            line = line.rstrip("\n")
            lines.append(line)
            self._all_lines.append(line)
            if line.startswith(token):
                return lines

    def new_game(self) -> None:
        self._send("ucinewgame")
        self._send("isready")
        self._wait_for("readyok")

    def search_movetime(self, fen: str, movetime_ms: int) -> None:
        self._send(f"position fen {fen}")
        self._send(f"go movetime {movetime_ms}")
        self._wait_for("bestmove")

    def quit(self) -> list[str]:
        self._send("quit")
        timer = threading.Timer(10, self._force_kill)
        timer.start()
        try:
            remaining = self._stdout.read()
            if remaining:
                for line in remaining.splitlines():
                    self._all_lines.append(line)
            self.proc.wait(timeout=10)
        except Exception:
            self._force_kill()
        finally:
            timer.cancel()
        return self._all_lines

    def _force_kill(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()


def run_tc(
    binary: str,
    fens: list[str],
    movetime_ms: int,
    threads: int,
    hash_mb: int,
    tc_label: str,
) -> list[str]:
    """Run all positions at one TC, return all engine output lines."""
    engine = SimpleEngine(binary, threads, hash_mb)

    for idx, fen in enumerate(fens):
        engine.new_game()
        print(
            f"  [{tc_label}] position {idx + 1}/{len(fens)}, "
            f"movetime={movetime_ms}ms",
            file=sys.stderr,
            flush=True,
        )
        engine.search_movetime(fen, movetime_ms)

    return engine.quit()


def extract_csv_section(lines: list[str]) -> list[str]:
    """Extract lines between CORR_SATURATION_CSV_START/END markers."""
    inside = False
    result: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped == "CORR_SATURATION_CSV_START":
            inside = True
            continue
        if stripped == "CORR_SATURATION_CSV_END":
            break
        if inside and stripped:
            result.append(stripped)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run correction saturation instrumentation"
    )
    parser.add_argument("binary", help="Path to instrumented binary")
    parser.add_argument(
        "--tc",
        nargs="+",
        default=["10+0.1", "80+0.8", "180+1.8"],
        help="Time controls (default: STC LTC VVLTC)",
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
        "--hash", type=int, default=128, help="Hash size in MB (default: 128)"
    )
    args = parser.parse_args()

    fens = load_positions()

    print(f"Binary: {args.binary}", file=sys.stderr)
    print(
        f"Positions: {len(fens)} from UHO_Lichess_4852_v1.epd (seed={SEED})",
        file=sys.stderr,
    )
    print(
        f"Threads: {args.threads}, Hash: {args.hash}MB",
        file=sys.stderr,
    )
    for i, fen in enumerate(fens):
        print(f"  [{i}] {fen}", file=sys.stderr)

    for tc_str in args.tc:
        base_ms, inc_ms = parse_tc(tc_str)
        movetime = compute_movetime(base_ms, inc_ms)
        tc_label = f"{tc_str} {args.threads}T"

        print(
            f"\n=== TC {tc_str}, {args.threads}T, movetime={movetime}ms ===",
            file=sys.stderr,
        )

        lines = run_tc(
            args.binary, fens, movetime, args.threads, args.hash, tc_label
        )
        csv_lines = extract_csv_section(lines)

        print(f"\n--- {tc_label} (movetime={movetime}ms) ---")
        for csv_line in csv_lines:
            print(csv_line)
        print()


if __name__ == "__main__":
    main()

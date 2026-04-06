"""Measure maxRootDepth progression across a simulated game.

Methodology matches nmp-mrd instrumentation: UHO book positions (seed=1),
proper movetimes (65 moves/game), PGO binary.

Runs N positions sequentially in one engine process (no ucinewgame between
them) to simulate a game. Records per-move rootDepth (final info depth)
and tracks the running maximum (= maxRootDepth after that move).

Usage:
    python measure_maxrootdepth.py <binary> [options]

Examples:
    python measure_maxrootdepth.py stockfish.exe --tc 5+0.05 --threads 8
    python measure_maxrootdepth.py stockfish.exe --tc 20+0.2 --threads 8
    python measure_maxrootdepth.py stockfish.exe --tc 10+0.1 --threads 1
    python measure_maxrootdepth.py stockfish.exe --tc 5+0.05 10+0.1 20+0.2 60+0.6 --threads 8
"""

import argparse
import random
import re
import subprocess
import sys
import threading

from shared.path_utils import validated_input_path

BOOK_PATH = r"C:\books\UHO_Lichess_4852_v1.epd"
SEED = 1
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


def load_positions(count: int) -> list[str]:
    """Load positions from UHO book with seed=1."""
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
    return rng.sample(all_fens, min(count, len(all_fens)))


class SimpleEngine:
    """Minimal UCI engine wrapper for sequential searches without reset."""

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
        """Read lines until token found. Return all lines read."""
        lines: list[str] = []
        while True:
            line = self._stdout.readline()
            if not line:
                raise RuntimeError(f"EOF before '{token}'")
            line = line.rstrip("\n")
            lines.append(line)
            if line.startswith(token):
                return lines

    def search_movetime(self, fen: str, movetime_ms: int) -> int:
        """Search a position and return the final depth reached."""
        self._send(f"position fen {fen}")
        self._send(f"go movetime {movetime_ms}")
        lines = self._wait_for("bestmove")
        last_depth = 0
        for line in lines:
            m = re.match(r"info depth (\d+) seldepth (\d+)", line)
            if m:
                last_depth = int(m.group(1))
        return last_depth

    def quit(self) -> None:
        """Send quit and wait for process to exit."""
        self._send("quit")
        timer = threading.Timer(10, self._force_kill)
        timer.start()
        try:
            self.proc.wait(timeout=10)
        except Exception:
            self._force_kill()
        finally:
            timer.cancel()

    def _force_kill(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()


def run_game_simulation(
    binary: str,
    fens: list[str],
    movetime_ms: int,
    threads: int,
    hash_mb: int,
    tc_label: str,
) -> list[tuple[int, int, int]]:
    """Run positions sequentially, return [(move#, rootDepth, maxRootDepth)]."""
    engine = SimpleEngine(binary, threads, hash_mb)
    results: list[tuple[int, int, int]] = []
    max_root_depth = 0

    for idx, fen in enumerate(fens):
        depth = engine.search_movetime(fen, movetime_ms)
        if depth > max_root_depth:
            max_root_depth = depth
        results.append((idx + 1, depth, max_root_depth))
        if (idx + 1) % 10 == 0 or idx == 0:
            print(
                f"  [{tc_label}] move {idx + 1}/{len(fens)}: "
                f"depth={depth}, maxRootDepth={max_root_depth}",
                file=sys.stderr,
                flush=True,
            )

    engine.quit()
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure maxRootDepth progression across a simulated game"
    )
    parser.add_argument("binary", help="Path to Stockfish binary")
    parser.add_argument(
        "--tc",
        nargs="+",
        default=["5+0.05", "20+0.2"],
        help="Time controls to test (default: 5+0.05 20+0.2)",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=8,
        choices=range(1, 1025),
        metavar="N",
        help="Thread count, 1-1024 (default: 8)",
    )
    parser.add_argument(
        "--hash", type=int, default=128, help="Hash size in MB (default: 128)"
    )
    parser.add_argument(
        "--moves",
        type=int,
        default=30,
        help="Number of moves to simulate (default: 30)",
    )
    args = parser.parse_args()

    fens = load_positions(args.moves)

    print(f"Binary: {args.binary}")
    print(f"Positions: {len(fens)} from UHO_Lichess_4852_v1.epd (seed={SEED})")
    print(f"Threads: {args.threads}, Hash: {args.hash}MB")
    print(f"Moves per game assumed: {MOVES_PER_GAME}")
    print()

    for tc_str in args.tc:
        base_ms, inc_ms = parse_tc(tc_str)
        movetime = compute_movetime(base_ms, inc_ms)
        tc_label = f"{tc_str} {args.threads}T"

        print(f"=== TC {tc_str}, {args.threads}T, movetime={movetime}ms ===")
        print(
            f"  Formula: {base_ms}ms / {MOVES_PER_GAME} + {inc_ms}ms = {movetime}ms"
        )

        results = run_game_simulation(
            args.binary, fens, movetime, args.threads, args.hash, tc_label
        )

        print(f"\n  {'Move':>4} | {'rootDepth':>9} | {'maxRootDepth':>12}")
        print(f"  {'----':>4} | {'---------':>9} | {'------------':>12}")
        for move_num, depth, mrd in results:
            print(f"  {move_num:>4} | {depth:>9} | {mrd:>12}")

        final_mrd = results[-1][2] if results else 0
        depths = [r[1] for r in results]
        print(f"\n  Per-move depth: min={min(depths)} max={max(depths)} "
              f"median={sorted(depths)[len(depths)//2]}")
        print(f"  maxRootDepth after {len(results)} moves: {final_mrd}")

        # Show progression at key points
        milestones = [1, 5, 10, 15, 20, 25, 30]
        print(f"\n  maxRootDepth progression:")
        for m in milestones:
            if m <= len(results):
                print(f"    After move {m:>2}: {results[m-1][2]}")

        print()


if __name__ == "__main__":
    main()

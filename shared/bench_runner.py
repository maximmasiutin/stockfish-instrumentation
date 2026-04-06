"""Shared utilities for running Stockfish bench and streaming output.

Version 1.0
Copyright 2026 Maxim Masiutin.
License: GPL-3.0

Provides run_bench() for running an instrumented Stockfish binary at a given
depth and thread count.  The caller is responsible for parsing the output lines.

Example:
    from shared.bench_runner import run_bench

    lines, timed_out = run_bench("./stockfish", depth=10, threads=8)
    for line in lines:
        if line.startswith("overlap,"):
            print(line)
"""

import os
import random
import subprocess
import sys
import tempfile
import threading

DEFAULT_EXE = "stockfish.exe" if sys.platform == "win32" else "./stockfish"
DEFAULT_TIMEOUT_S = 7200


def pick_random_fen(book_path: str, seed: int | None = None) -> str:
    """Pick a random FEN from an EPD book file."""
    with open(book_path, "r", encoding="utf-8") as f:
        lines = [ln.strip() for ln in f if ln.strip()]
    rng = random.Random(seed)
    fen = rng.choice(lines)
    if ";" in fen:
        fen = fen[: fen.index(";")].strip()
    return fen


def run_bench(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    exe: str,
    depth: int,
    threads: int = 8,
    hash_mb: int = 256,
    fen: str | None = None,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    progress_prefix: str = "",
    extra_env: dict[str, str] | None = None,
) -> tuple[list[str], bool]:
    """Run Stockfish bench at *depth* with *threads* worker threads.

    Sets ``BENCH_DEPTH`` in the environment so instrumented binaries can
    identify the current depth in their output.  Additional environment
    variables can be passed via *extra_env*.

    If *fen* is provided, it is written to a secure temp file and passed
    as the fen_file argument to bench (one position per run). Otherwise,
    the default bench positions are used.

    Args:
        exe: Path to the Stockfish executable.
        depth: Search depth passed to ``bench``.
        threads: Thread count passed to ``bench``.
        hash_mb: Hash size in MB passed to ``bench``.
        fen: Optional single FEN position (one position per run).
        timeout_s: Kill the process after this many seconds (default 7200).
        progress_prefix: Prefix for progress lines printed to stdout.
        extra_env: Additional environment variables merged into the process env.

    Returns:
        A tuple ``(lines, timed_out)`` where *lines* is the list of stdout
        lines (newline stripped) and *timed_out* is True if the watchdog fired.
    """
    fen_file: str | None = None
    if fen is not None:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", delete=False, suffix=".txt"
        ) as tmp:
            tmp.write(fen + "\n")
            fen_file = tmp.name
        cmd = [exe, "bench", str(hash_mb), str(threads), str(depth), fen_file]
    else:
        cmd = [exe, "bench", str(hash_mb), str(threads), str(depth)]
    env = os.environ.copy()
    env["BENCH_DEPTH"] = str(depth)
    if extra_env:
        env.update(extra_env)

    proc = subprocess.Popen(  # pylint: disable=consider-using-with
        cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env
    )

    timed_out_event = threading.Event()

    def _kill_on_timeout() -> None:
        if proc.poll() is None:
            timed_out_event.set()
            proc.kill()

    timer = threading.Timer(timeout_s, _kill_on_timeout)
    timer.start()

    lines: list[str] = []
    bestmove_count = 0
    try:
        if proc.stdout is None:
            raise RuntimeError("stdout pipe not available")
        for line in proc.stdout:
            line = line.rstrip("\n")
            lines.append(line)
            if line.startswith("bestmove"):
                bestmove_count += 1
                tag = f"{progress_prefix} " if progress_prefix else ""
                print(
                    f"  {tag}d={depth} t={threads} pos {bestmove_count}/51",
                    flush=True,
                )
        proc.wait()
    finally:
        timer.cancel()
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        if fen_file is not None:
            try:
                os.unlink(fen_file)
            except OSError:
                pass

    if timed_out_event.is_set():
        print(
            f"TIMEOUT after {timeout_s}s (depth={depth} threads={threads})",
            file=sys.stderr,
            flush=True,
        )
        return lines, True

    if proc.returncode != 0:
        print(
            f"bench failed (exit {proc.returncode}, depth={depth} threads={threads})",
            file=sys.stderr,
            flush=True,
        )
        return lines, False

    return lines, False

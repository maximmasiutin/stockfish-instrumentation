"""UCI engine subprocess manager for instrumented Stockfish binaries.

Version 1.0
Copyright 2026 Maxim Masiutin.
License: GPL-3.0

Manages a long-running Stockfish process via UCI protocol. Sends positions
and go commands, waits for bestmove, and collects stdout for post-processing.

Example:
    from shared.uci_engine import UCIEngine

    engine = UCIEngine("./stockfish", threads=8, hash_mb=256)
    engine.go_depth("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", 20)
    lines = engine.quit()
    for line in lines:
        if line.startswith("overlap,"):
            print(line)
"""

import subprocess
import sys
import threading

DEFAULT_EXE = "stockfish.exe" if sys.platform == "win32" else "./stockfish"


class UCIEngine:
    """Manage a Stockfish UCI process for instrumentation runs."""

    def __init__(
        self,
        exe: str = DEFAULT_EXE,
        threads: int = 1,
        hash_mb: int = 256,
    ) -> None:
        self.proc = subprocess.Popen(  # pylint: disable=consider-using-with
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
        self._collected: list[str] = []

        self._send("uci")
        self._wait_for("uciok")
        self._send(f"setoption name Threads value {threads}")
        self._send(f"setoption name Hash value {hash_mb}")
        self._send("isready")
        self._wait_for("readyok")

    def _send(self, cmd: str) -> None:
        self._stdin.write(cmd + "\n")
        self._stdin.flush()

    def _wait_for(self, token: str) -> None:
        """Read lines until one starts with *token*. Collect all lines."""
        while True:
            line = self._stdout.readline()
            if not line:
                raise RuntimeError(
                    f"Engine EOF before '{token}' (collected {len(self._collected)} lines)"
                )
            line = line.rstrip("\n")
            self._collected.append(line)
            if line.startswith(token):
                return

    def go_depth(self, fen: str, depth: int) -> None:
        """Search a position to a fixed depth."""
        self._send(f"position fen {fen}")
        self._send(f"go depth {depth}")
        self._wait_for("bestmove")

    def go_movetime(self, fen: str, movetime_ms: int) -> None:
        """Search a position for a fixed time."""
        self._send(f"position fen {fen}")
        self._send(f"go movetime {movetime_ms}")
        self._wait_for("bestmove")

    def quit(self, timeout_s: int = 30) -> list[str]:
        """Send quit and return all collected stdout lines."""
        self._send("quit")
        timer = threading.Timer(timeout_s, self._force_kill)
        timer.start()
        try:
            remaining = self._stdout.read()
            if remaining:
                for line in remaining.splitlines():
                    self._collected.append(line)
            self.proc.wait(timeout=timeout_s)
        except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            self._force_kill()
        finally:
            timer.cancel()
        return self._collected

    def _force_kill(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()

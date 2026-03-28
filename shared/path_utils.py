"""Path validation utilities for CLI argument sanitization."""

import sys
from pathlib import Path


def validated_input_path(raw: str) -> Path:
    """Resolve and validate a CLI input path. Exit if it does not exist."""
    p = Path(raw).resolve()
    if not p.exists():
        print(f"Error: input path does not exist: {p}", file=sys.stderr)
        sys.exit(1)
    return p


def validated_output_path(raw: str) -> Path:
    """Resolve and validate a CLI output path. Exit if parent dir missing."""
    p = Path(raw).resolve()
    if not p.parent.exists():
        print(
            f"Error: parent directory does not exist: {p.parent}", file=sys.stderr
        )
        sys.exit(1)
    return p

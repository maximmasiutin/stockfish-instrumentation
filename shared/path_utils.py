"""Path validation utilities for CLI argument sanitization."""

import sys
from pathlib import Path


def validated_input_path(raw: str) -> Path:
    """Resolve and validate a CLI input path. Exit if not an existing file."""
    p = Path(raw).resolve(strict=False)
    if not p.is_file():
        if not p.exists():
            print(f"Error: input path does not exist: {p}", file=sys.stderr)
        else:
            print(f"Error: input path is not a file: {p}", file=sys.stderr)
        sys.exit(1)
    return p


def validated_output_path(raw: str) -> Path:
    """Resolve and validate a CLI output path. Exit if parent dir missing."""
    p = Path(raw).resolve(strict=False)
    if p.is_dir():
        print(f"Error: output path is a directory: {p}", file=sys.stderr)
        sys.exit(1)
    if not p.parent.is_dir():
        print(
            f"Error: parent directory does not exist: {p.parent}", file=sys.stderr
        )
        sys.exit(1)
    return p

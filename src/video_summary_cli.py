#!/usr/bin/env python
"""Canonical entry point for video summary generation."""

from pathlib import Path
import sys

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from video_summary.cli import main


if __name__ == "__main__":
    main()

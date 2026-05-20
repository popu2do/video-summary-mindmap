#!/usr/bin/env python
"""Thin wrapper for the local video-summary-mindmap skill."""

from __future__ import annotations

import runpy
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / ".agents" / "skill" / "video-summary-mindmap" / "scripts" / "video_summary.py"

runpy.run_path(str(SCRIPT), run_name="__main__")

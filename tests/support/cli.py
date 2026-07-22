from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from typing import Iterable, Mapping


REPO_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_CLI = REPO_ROOT / "src" / "video_summary_cli.py"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"


def run_canonical_cli(
    *args: str,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    timeout: float = 10.0,
) -> subprocess.CompletedProcess[str]:
    """Run the migration target as a black-box CLI from an isolated cwd."""
    command: Iterable[str] = (sys.executable, str(CANONICAL_CLI), *args)
    child_env = os.environ.copy()
    if env:
        child_env.update(env)
    try:
        return subprocess.run(
            list(command),
            cwd=cwd,
            env=child_env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        return subprocess.CompletedProcess(
            list(command),
            124,
            stdout=error.stdout or "",
            stderr=f"canonical CLI timed out after {timeout:g}s",
        )


def assert_cli_succeeded(test_case, result: subprocess.CompletedProcess[str]) -> None:
    """Attach both streams when a CLI contract test fails."""
    test_case.assertEqual(
        result.returncode,
        0,
        msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
    )

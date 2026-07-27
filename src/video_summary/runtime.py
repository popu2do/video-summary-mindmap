from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import tempfile


@dataclass
class RunWorkspace:
    """Own the private filesystem area for one summary run."""

    path: Path
    _cleaned: bool = False

    @classmethod
    def create(cls, out_root: Path) -> "RunWorkspace":
        workspace_parent = Path(out_root).expanduser().resolve().parent
        workspace_parent.mkdir(parents=True, exist_ok=True)
        return cls(
            Path(tempfile.mkdtemp(prefix=".video-summary-", dir=workspace_parent))
        )

    def preserve_to(self, destination: Path) -> None:
        """Copy this run's private files to an explicit diagnostic destination."""
        if self._cleaned:
            raise RuntimeError("运行工作区已清理，无法保留中间态。")
        destination = destination.expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise FileExistsError(f"调试快照目标已存在：{destination}")
        shutil.copytree(self.path, destination)

    def cleanup(self) -> None:
        if self._cleaned:
            return
        shutil.rmtree(self.path, ignore_errors=True)
        self._cleaned = True

    def __enter__(self) -> "RunWorkspace":
        return self

    def __exit__(self, _exc_type: object, _exc_value: object, _traceback: object) -> None:
        self.cleanup()

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from video_summary import llm, outputs


class IntermediateArtifactConvergenceTests(unittest.TestCase):
    def test_write_outputs_keeps_only_the_draft_consumed_by_refinement(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            outputs.write_outputs(
                {"title": "测试视频", "uploader": "作者", "duration": 90},
                "https://example.test/video",
                out_dir,
                "这是一段足够长的逐字稿内容，用于验证中间产物只保留精校所需的草稿。",
                "zh",
                "compact",
            )

            self.assertTrue((out_dir / "_internal" / "summary_draft.md").is_file())
            self.assertFalse((out_dir / "_internal" / "mindmap_draft.mmd").exists())
            self.assertFalse((out_dir / "_internal" / "metadata.json").exists())

    def test_long_lecture_chunk_summaries_are_single_run_state_not_disk_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            with mock.patch.object(
                llm,
                "call_llm",
                side_effect=["分段一摘要", "最终摘要"],
            ):
                result = llm.refine_long_lecture_with_llm(
                    title="长课程",
                    source="https://example.test/video",
                    author="作者",
                    duration="01:00:00",
                    out_dir=out_dir,
                    transcript="第一段内容足够长。第二段内容也足够长。",
                    subtitle_lang="zh",
                    draft_summary="已有草稿",
                    model="test-model",
                    api_kind="responses",
                    chunk_chars=12,
                )

            self.assertEqual(result, "最终摘要")
            self.assertFalse((out_dir / "_internal" / "summary_chunks.json").exists())


if __name__ == "__main__":
    unittest.main()

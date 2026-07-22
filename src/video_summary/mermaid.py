from __future__ import annotations

import re

def extract_mermaid(markdown: str) -> str:
    match = re.search(r"```mermaid\s+(.*?)```", markdown, flags=re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1)
    match = re.search(r"(^mindmap\s+.*)", markdown, flags=re.DOTALL | re.MULTILINE)
    return match.group(1) if match else ""

def mindmap_text(value: str, limit: int = 36) -> str:
    value = re.sub(r"[\r\n\t]+", " ", value).strip()
    value = re.sub(r"[(){}\[\]\"`]", "", value)
    return value[:limit] or "未命名"

def build_mermaid(title: str, sections: list[str], key_points: list[str], terms: list[str]) -> str:
    lines = ["mindmap", f"  root(({mindmap_text(title, 28)}))", "    分段大纲"]
    lines.extend(f"      {mindmap_text(item)}" for item in sections[:6])
    lines.append("    关键观点")
    lines.extend(f"      {mindmap_text(item)}" for item in key_points[:6])
    lines.append("    高频术语")
    lines.extend(f"      {mindmap_text(item, 18)}" for item in terms[:8])
    return "\n".join(lines)

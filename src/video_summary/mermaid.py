from __future__ import annotations

import re


_FENCED_MERMAID = re.compile(
    r"```mermaid\b\s*(.*?)```",
    flags=re.DOTALL | re.IGNORECASE,
)
_BARE_MINDMAP = re.compile(
    r"(?im)^[ \t]*mindmap[ \t]*(?:\r?\n|$)(?:[ \t]+.*(?:\r?\n|$))*"
)


def extract_mermaid(markdown: str) -> str:
    match = _FENCED_MERMAID.search(markdown)
    if match:
        return match.group(1)
    match = _BARE_MINDMAP.search(markdown)
    return match.group(0).strip() if match else ""


def is_valid_mindmap(value: str) -> bool:
    """Return whether value satisfies the published mindmap contract."""
    lines = [line for line in value.splitlines() if line.strip()]
    if not lines or lines[0].strip().casefold() != "mindmap":
        return False
    return any(line[:1].isspace() for line in lines[1:])


def remove_bare_mindmaps(markdown: str) -> str:
    """Remove standalone bare mindmap blocks without consuming following prose."""
    fenced_blocks: list[str] = []

    def protect(match: re.Match[str]) -> str:
        fenced_blocks.append(match.group(0))
        return f"\x00MERMAID_{len(fenced_blocks) - 1}\x00"

    masked = _FENCED_MERMAID.sub(protect, markdown)
    cleaned = _BARE_MINDMAP.sub("", masked)
    for index, block in enumerate(fenced_blocks):
        cleaned = cleaned.replace(f"\x00MERMAID_{index}\x00", block)
    return cleaned


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

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from .config import UserFacingError, fail
from .sources import safe_display_name
from .transcript import normalize_text


def extract_document_text(path: Path) -> str:
    """Extract text from PDF or OOXML documents without changing output layout."""
    display_name = safe_display_name(str(path))
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader  # type: ignore
        except ImportError:
            fail(f"读取 PDF 需要安装 pypdf：python -m pip install pypdf（文件：{display_name}）")
        try:
            reader = PdfReader(str(path))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception:
            fail(f"PDF 文件损坏或无法读取：{display_name}")
        text = normalize_text(text)
        if not text:
            fail(f"PDF 未提取到文本层，图像型 PDF 暂不支持：{display_name}")
        return text
    if suffix in {".doc", ".docx"}:
        try:
            with zipfile.ZipFile(path) as archive:
                document_xml = archive.read("word/document.xml")
        except (KeyError, zipfile.BadZipFile) as error:
            fail(f"仅支持 OOXML 格式的 .doc/.docx 文档：{display_name} ({error})")
        try:
            root = ET.fromstring(document_xml)
        except ET.ParseError as error:
            fail(f"DOC 文档 XML 解析失败：{display_name} ({error})")
        namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        paragraphs = []
        for paragraph in root.iter(namespace + "p"):
            value = "".join(node.text or "" for node in paragraph.iter(namespace + "t"))
            if value.strip():
                paragraphs.append(value)
        return normalize_text("\n".join(paragraphs))
    fail(f"不支持的文档格式：{display_name}（扩展名：{suffix}）")
    return ""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from .config import fail
from .transcript import normalize_text

def extract_document_text(path: Path) -> str:
    """Extract text from PDF or OOXML documents without changing output layout."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader  # type: ignore
        except ImportError:
            fail("读取 PDF 需要安装 pypdf：python -m pip install pypdf")
        reader = PdfReader(str(path))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        return normalize_text(text)
    if suffix in {".doc", ".docx"}:
        try:
            with zipfile.ZipFile(path) as archive:
                document_xml = archive.read("word/document.xml")
        except (KeyError, zipfile.BadZipFile) as error:
            fail(f"仅支持 OOXML 格式的 .doc/.docx 文档：{path} ({error})")
        try:
            root = ET.fromstring(document_xml)
        except ET.ParseError as error:
            fail(f"DOC 文档 XML 解析失败：{path} ({error})")
        namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        paragraphs = []
        for paragraph in root.iter(namespace + "p"):
            value = "".join(node.text or "" for node in paragraph.iter(namespace + "t"))
            if value.strip():
                paragraphs.append(value)
        return normalize_text("\n".join(paragraphs))
    fail(f"不支持的文档格式：{path.suffix}")
    return ""

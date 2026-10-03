"""Project MinerU 4.0 artifacts into the 3.x fields ThinkExtract and ThinkDoc read."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


class ProjectionError(Exception):
    """The engine output cannot satisfy the legacy contract."""


_MD_IMAGE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
_HTML_IMAGE = re.compile(r"""src\s*=\s*["']([^"']+)["']""", re.IGNORECASE)

_V1_TYPES = {
    "text",
    "image",
    "table",
    "equation",
    "list",
    "code",
    "chart",
    "discarded",
    "abandon",
    "page_footnote",
    "header",
    "footer",
    "page_header",
    "page_footer",
    "page_number",
}

_TITLE_TYPES = {"title", "doc_title", "paragraph_title"}
_DISCARD_TYPES = {
    "discarded",
    "abandon",
    "page_header",
    "page_footer",
    "page_number",
    "header",
    "footer",
    "aside_text",
}
_LEGACY_DISCARD_TYPE = {
    "page_header": "header",
    "header": "header",
    "page_footer": "footer",
    "footer": "footer",
    "page_number": "page_number",
    "discarded": "discarded",
    "abandon": "discarded",
    "aside_text": "discarded",
}
_EQUATION_TYPES = {"equation", "interline_equation"}


@dataclass
class Projection:
    markdown: str
    content_list: list[dict[str, Any]]
    middle_pdf_info: dict[str, Any]
    image_names: list[str] = field(default_factory=list)
    native_middle: dict[str, Any] | None = None
    docling_document: dict[str, Any] | None = None


def project_docling(*, markdown: str, document: dict[str, Any] | None) -> Projection:
    if not isinstance(document, dict) or not document:
        raise ProjectionError("docling result has no document")
    return Projection(
        markdown=markdown or "",
        content_list=[],
        middle_pdf_info={"pdf_info": []},
        docling_document=document,
    )


def project_mineru(
    *,
    markdown: str,
    middle: dict[str, Any] | None = None,
    content_list: list[Any] | None = None,
) -> Projection:
    native = middle if isinstance(middle, dict) else None
    pages = _pages(native)
    items = _content_list(content_list, pages)
    pdf_info = _pdf_info(pages, items, _layout_page_sizes(native))
    if not items and not pdf_info:
        raise ProjectionError("mineru output has neither content_list nor pages")
    text = markdown or ""
    if "data:image" in text or any("data:image" in str(item.get("table_body") or "") for item in items):
        raise ProjectionError("result still embeds data:image")
    names = _image_names(text, items)
    middle_out = {"pdf_info": pdf_info}
    if "schema" in middle_out:
        raise ProjectionError("legacy middle_json must not carry schema")
    return Projection(
        markdown=text,
        content_list=items,
        middle_pdf_info=middle_out,
        image_names=names,
        native_middle=native,
    )


def _content_list(raw: list[Any] | None, pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if _is_v1(raw):
        assert raw is not None
        return [dict(item) for item in raw if isinstance(item, dict)]
    if not pages:
        if raw:
            raise ProjectionError("content_list is not legacy v1 and middle has no pages")
        return []
    items: list[dict[str, Any]] = []
    for page in pages:
        page_idx = int(page.get("page_idx") or 0)
        blocks = page.get("blocks") or []
        if not isinstance(blocks, list):
            raise ProjectionError("page.blocks must be a list")
        for block in blocks:
            if not isinstance(block, dict):
                continue
            item = _map_block(block, page_idx)
            if item is not None:
                items.append(item)
    return items


def _is_v1(raw: list[Any] | None) -> bool:
    if not raw:
        return False
    if not all(isinstance(item, dict) and isinstance(item.get("type"), str) for item in raw):
        return False
    return all(str(item["type"]) in _V1_TYPES for item in raw if isinstance(item, dict))


def _pages(middle: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not middle:
        return []
    pages = middle.get("pages")
    if isinstance(pages, list):
        return [page for page in pages if isinstance(page, dict)]
    pdf_info = middle.get("pdf_info")
    if isinstance(pdf_info, list):
        return [page for page in pdf_info if isinstance(page, dict)]
    return []


def _map_block(block: dict[str, Any], page_idx: int) -> dict[str, Any] | None:
    kind = str(block.get("type") or "")
    text = _block_text(block)
    bbox = block.get("bbox") if isinstance(block.get("bbox"), list) else None
    item: dict[str, Any] | None = None
    if kind in _TITLE_TYPES:
        item = {"type": "text", "text": text, "text_level": int(block.get("level") or block.get("text_level") or 1)}
    elif kind in _EQUATION_TYPES:
        item = {"type": "equation", "text": text, "text_format": "latex"}
    elif kind == "image":
        item = {"type": "image", "img_path": _image_path(block)}
    elif kind == "table":
        body_node = _typed_child(block, "table_body")
        body = ""
        if isinstance(body_node, dict) and isinstance(body_node.get("content"), str):
            body = body_node["content"]
        elif isinstance(block.get("table_body"), str):
            body = block["table_body"]
        else:
            body = text
        image = _image_path(body_node) if isinstance(body_node, dict) else ""
        item = {"type": "table", "table_body": body, "img_path": image or _image_path(block)}
        caption_node = _typed_child(block, "table_caption") or {}
        caption = _span_text(caption_node.get("content"))
        if caption:
            item["table_caption"] = [caption]
    elif kind == "chart":
        item = {"type": "chart", "img_path": _image_path(block)}
    elif kind in {"text", "paragraph"}:
        item = {"type": "text", "text": text}
    elif kind in _DISCARD_TYPES:
        item = {"type": "discarded", "text": text}
    elif kind == "list":
        item = {"type": "list", "list_items": block.get("list_items") or ([text] if text else [])}
    elif kind == "code":
        item = {"type": "code", "code_body": block.get("code_body") or text}
    elif kind == "index":
        item = {"type": "text", "text": text}
    else:
        return None
    item["page_idx"] = page_idx
    if bbox is not None:
        item["bbox"] = bbox
    return item


def _block_text(block: dict[str, Any]) -> str:
    if isinstance(block.get("text"), str) and block["text"]:
        return block["text"]
    return _span_text(block.get("content"))


def _span_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(_span_text(span) for span in content)
    if isinstance(content, dict):
        if "content" in content:
            return _span_text(content.get("content"))
        value = content.get("text")
        return value if isinstance(value, str) else ""
    return ""


def _image_path(block: dict[str, Any]) -> str:
    for key in ("img_path", "image_path", "path"):
        value = block.get(key)
        if isinstance(value, str) and value and not value.startswith("data:"):
            return value
    return ""


def _layout_page_sizes(middle: dict[str, Any] | None) -> dict[int, list[Any]]:
    if not isinstance(middle, dict):
        return {}
    extensions = middle.get("extensions")
    layout = extensions.get("docvortex_layout") if isinstance(extensions, dict) else None
    pages = layout.get("pages") if isinstance(layout, dict) else None
    sizes: dict[int, list[Any]] = {}
    if not isinstance(pages, list):
        return sizes
    for page in pages:
        if not isinstance(page, dict):
            continue
        width = page.get("width_pt")
        height = page.get("height_pt")
        if isinstance(width, (int, float)) and isinstance(height, (int, float)):
            sizes[int(page.get("page_idx") or 0)] = [width, height]
    return sizes


def _typed_child(block: dict[str, Any], kind: str) -> dict[str, Any] | None:
    content = block.get("content")
    if not isinstance(content, list):
        return None
    for child in content:
        if isinstance(child, dict) and child.get("type") == kind:
            return child
    return None


def _pdf_info(
    pages: list[dict[str, Any]],
    items: list[dict[str, Any]],
    page_sizes: dict[int, list[Any]] | None = None,
) -> list[dict[str, Any]]:
    if pages:
        info: list[dict[str, Any]] = []
        for index, page in enumerate(pages):
            page_idx = int(page.get("page_idx") or index)
            size = page.get("page_size")
            if not isinstance(size, list) or len(size) < 2:
                width = page.get("width") or 0
                height = page.get("height") or 0
                size = [width, height]
            if (not size or size[0] in (0, 0.0)) and page_sizes and page_idx in page_sizes:
                size = page_sizes[page_idx]
            discarded = _discarded_from_page(page, page_idx)
            if not discarded:
                discarded = _discarded_from_items(items, page_idx)
            info.append(
                {
                    "page_idx": page_idx,
                    "page_size": size[:2],
                    "discarded_blocks": discarded,
                }
            )
        return info
    page_ids = sorted({int(item.get("page_idx") or 0) for item in items})
    return [
        {
            "page_idx": page_idx,
            "page_size": [0, 0],
            "discarded_blocks": _discarded_from_items(items, page_idx),
        }
        for page_idx in page_ids
    ]


def _discarded_from_page(page: dict[str, Any], page_idx: int) -> list[dict[str, Any]]:
    blocks = page.get("discarded_blocks")
    source = blocks if isinstance(blocks, list) else page.get("blocks") or []
    found: list[dict[str, Any]] = []
    if not isinstance(source, list):
        return found
    for block in source:
        if not isinstance(block, dict):
            continue
        kind = str(block.get("type") or "discarded")
        if isinstance(blocks, list) or kind in _DISCARD_TYPES:
            legacy = _legacy_discarded_block(block)
            if legacy is not None:
                found.append(legacy)
    return found


def _discarded_from_items(items: list[dict[str, Any]], page_idx: int) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for item in items:
        if int(item.get("page_idx") or 0) != page_idx:
            continue
        if str(item.get("type") or "") not in _DISCARD_TYPES and item.get("type") != "discarded":
            continue
        legacy = _legacy_discarded_block(item)
        if legacy is not None:
            found.append(legacy)
    return found


def _legacy_discarded_block(block: dict[str, Any]) -> dict[str, Any] | None:
    """Emit the 3.x block ThinkExtract reads: lines[].spans[].content."""
    lines = block.get("lines")
    if isinstance(lines, list) and lines:
        kind = str(block.get("type") or "discarded")
        entry: dict[str, Any] = {
            "type": _LEGACY_DISCARD_TYPE.get(kind, "discarded"),
            "lines": lines,
        }
        if isinstance(block.get("bbox"), list):
            entry["bbox"] = block["bbox"]
        return entry
    text = _block_text(block)
    if not text.strip():
        return None
    kind = str(block.get("type") or "discarded")
    line: dict[str, Any] = {"spans": [{"type": "text", "content": text}]}
    bbox = block.get("bbox") if isinstance(block.get("bbox"), list) else None
    if bbox is not None:
        line["bbox"] = bbox
    entry = {"type": _LEGACY_DISCARD_TYPE.get(kind, "discarded"), "lines": [line]}
    if bbox is not None:
        entry["bbox"] = bbox
    return entry


def _image_names(markdown: str, items: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()

    def add(path: str) -> None:
        if not path or path.startswith("data:") or path.startswith("http://") or path.startswith("https://"):
            return
        filename = path.rsplit("/", 1)[-1].split("?", 1)[0].split("#", 1)[0]
        if not filename or filename in seen:
            return
        seen.add(filename)
        names.append(filename)

    for match in _MD_IMAGE.finditer(markdown):
        add(match.group(1).strip())
    for match in _HTML_IMAGE.finditer(markdown):
        add(match.group(1).strip())
    for item in items:
        path = item.get("img_path")
        if isinstance(path, str):
            add(path)
        body = item.get("table_body")
        if isinstance(body, str):
            for match in _HTML_IMAGE.finditer(body):
                add(match.group(1).strip())
    return names

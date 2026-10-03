"""Unpack a MinerU 4.0 self-contained result zip.

The zip is the only complete engine result. Markdown and middle JSON inside it
reference files under images/; they do not carry data: URLs.
"""

from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass
from io import BytesIO
from typing import Any

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$")


class BundleError(Exception):
    """The zip cannot be used as a complete parse result."""


@dataclass(frozen=True)
class ResultBundle:
    markdown: str
    middle: dict[str, Any]
    images: dict[str, bytes]


def open_result_zip(payload: bytes) -> ResultBundle:
    try:
        archive = zipfile.ZipFile(BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise BundleError("result zip is not a valid archive") from exc
    with archive:
        names = set(archive.namelist())
        if "markdown.md" not in names or "middle_json.json" not in names:
            raise BundleError("result zip is missing markdown.md or middle_json.json")
        markdown = archive.read("markdown.md").decode("utf-8")
        try:
            middle = json.loads(archive.read("middle_json.json").decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise BundleError("middle_json.json is not valid JSON") from exc
        if not isinstance(middle, dict):
            raise BundleError("middle_json.json must be an object")
        images = _image_files(archive, names)
    if "data:image" in markdown or _embeds_data_image(middle):
        raise BundleError("result zip still embeds data:image; images must be files")
    referenced = _referenced_names(markdown, middle)
    missing = sorted(name for name in referenced if name not in images)
    if missing:
        raise BundleError("result zip is missing image files: " + ", ".join(missing))
    return ResultBundle(markdown=markdown, middle=middle, images=images)


def _image_files(archive: zipfile.ZipFile, names: set[str]) -> dict[str, bytes]:
    images: dict[str, bytes] = {}
    for name in sorted(names):
        if not name.startswith("images/") or name.endswith("/"):
            continue
        relative = name[len("images/") :]
        if "/" in relative or not _NAME.fullmatch(relative):
            raise BundleError(f"unsafe image path in result zip: {name}")
        images[relative] = archive.read(name)
    return images


def _embeds_data_image(value: Any) -> bool:
    if isinstance(value, str):
        return "data:image" in value
    if isinstance(value, dict):
        return any(_embeds_data_image(item) for item in value.values())
    if isinstance(value, list):
        return any(_embeds_data_image(item) for item in value)
    return False


def _referenced_names(markdown: str, middle: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for match in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", markdown):
        names.add(_clean_ref(match.group(1)))
    for match in re.finditer(r"""src\s*=\s*["']([^"']+)["']""", markdown):
        names.add(_clean_ref(match.group(1)))
    _walk_refs(middle, names)
    names.discard("")
    return names


def _walk_refs(value: Any, names: set[str]) -> None:
    if isinstance(value, dict):
        for key in ("image_path", "img_path"):
            path = value.get(key)
            if isinstance(path, str):
                names.add(_clean_ref(path))
        content = value.get("content")
        if value.get("type") in {"table", "table_body", "chart"} and isinstance(content, str):
            for match in re.finditer(r"""src\s*=\s*["']([^"']+)["']""", content):
                names.add(_clean_ref(match.group(1)))
        for item in value.values():
            _walk_refs(item, names)
    elif isinstance(value, list):
        for item in value:
            _walk_refs(item, names)


def _clean_ref(path: str) -> str:
    cleaned = path.strip().split("?", 1)[0].split("#", 1)[0]
    if not cleaned or cleaned.startswith(("data:", "http://", "https://")):
        return ""
    if cleaned.startswith("images/"):
        cleaned = cleaned[len("images/") :]
    if "/" in cleaned or _NAME.fullmatch(cleaned) is None:
        return ""
    return cleaned

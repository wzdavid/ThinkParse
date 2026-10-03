"""Map the legacy task form onto a MinerU 4.0 tier."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class RequestRejected(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".jp2", ".webp", ".gif", ".bmp", ".tiff", ".tif"}
_PDF_SUFFIXES = {".pdf"}
_DOCILING_SUFFIXES = {".xml", ".tex", ".eml"}
_KNOWN_BACKENDS = {"pipeline", "basic", "flash", "standard", "advanced"}
_OCR_MODES = {"auto", "txt", "ocr"}


@dataclass(frozen=True)
class ParseOptions:
    tier: str
    ocr_mode: str
    engine: str
    legacy_backend: str
    lang: str
    formula_enable: bool
    table_enable: bool
    warnings: tuple[str, ...]


def form_bool(value: object, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def resolve_options(
    *,
    filename: str,
    backend: str | None,
    method: str | None,
    lang: str | None,
    formula_enable: object,
    table_enable: object,
    tier: str | None,
    legacy_allow_flash: bool,
    docling_enabled: bool = False,
    allow_native_tiers: bool = False,
    accepted_tiers: tuple[str, ...] = ("flash", "basic", "standard", "advanced"),
) -> ParseOptions:
    suffix = Path(filename or "").suffix.lower()
    if suffix in _DOCILING_SUFFIXES:
        if not docling_enabled:
            raise RequestRejected(
                400,
                f"{suffix} is reserved for the Docling route, which is not registered",
            )
        return ParseOptions(
            tier="basic",
            ocr_mode="auto",
            engine="docling",
            legacy_backend="docling",
            lang=(lang or "en").strip() or "en",
            formula_enable=form_bool(formula_enable, True),
            table_enable=form_bool(table_enable, True),
            warnings=(),
        )
    if suffix and suffix not in _PDF_SUFFIXES and suffix not in _IMAGE_SUFFIXES:
        raise RequestRejected(
            400,
            f"{suffix} is not enabled on the MinerU route",
        )

    requested = (tier or backend or "pipeline").strip().lower()
    if requested not in _KNOWN_BACKENDS:
        raise RequestRejected(400, f"unknown backend: {requested}")

    warnings: list[str] = []
    if requested in {"pipeline", "basic"}:
        resolved_tier = "basic"
        legacy_backend = "pipeline" if requested == "pipeline" or not backend else backend
        if requested == "basic":
            legacy_backend = "pipeline"
    elif requested == "flash":
        if not legacy_allow_flash and not allow_native_tiers:
            raise RequestRejected(
                400,
                "flash is disabled on the legacy API until projection fixtures pass; set LEGACY_ALLOW_FLASH=true",
            )
        resolved_tier = "flash"
        legacy_backend = "flash"
    elif requested == "advanced":
        if not allow_native_tiers:
            raise RequestRejected(400, "advanced is not available on the legacy API")
        resolved_tier = "advanced"
        legacy_backend = "advanced"
    else:
        resolved_tier = "standard"
        legacy_backend = "standard"
        warnings.append("standard ignores formula_enable and table_enable")

    if not backend or backend.strip().lower() == "pipeline":
        legacy_backend = "pipeline" if resolved_tier == "basic" else legacy_backend

    ocr_mode = (method or "auto").strip().lower()
    if ocr_mode not in _OCR_MODES:
        raise RequestRejected(400, f"unknown method: {ocr_mode}")

    formula = form_bool(formula_enable, True)
    table = form_bool(table_enable, True)
    if resolved_tier == "basic" and not formula:
        warnings.append("MinerU 4.0 basic has no formula switch; formula_enable was recorded only")
    if not table:
        warnings.append("MinerU 4.0 job API has no table switch; table_enable was recorded only")
    if resolved_tier not in accepted_tiers:
        raise RequestRejected(400, f"tier {resolved_tier} is not available in this deployment")

    return ParseOptions(
        tier=resolved_tier,
        ocr_mode=ocr_mode,
        engine="mineru",
        legacy_backend=legacy_backend if resolved_tier == "basic" else resolved_tier,
        lang=(lang or "ch").strip() or "ch",
        formula_enable=formula,
        table_enable=table,
        warnings=tuple(warnings),
    )

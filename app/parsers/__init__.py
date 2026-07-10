"""Pluggable statement parsers by card issuer."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Protocol

# Known issuers for the UI filter / upload picker (parsers may lag).
ISSUERS: dict[str, str] = {
    "amex": "American Express",
    "apple": "Apple Card",
    "citi": "Citi",
    "chase": "Chase",
    "capital_one": "Capital One",
    "discover": "Discover",
    "other": "Other",
}

DEFAULT_ISSUER = "amex"


class StatementParser(Protocol):
    issuer: str

    def parse(self, pdf_path: Path | str, filename: str | None = None) -> Any: ...


def _amex_parse(pdf_path: Path | str, filename: str | None = None):
    from ..parser import parse_amex_pdf

    statement = parse_amex_pdf(pdf_path, filename=filename)
    if hasattr(statement, "issuer"):
        statement.issuer = "amex"
    return statement


_REGISTRY: dict[str, Callable[..., Any]] = {
    "amex": _amex_parse,
}


def issuer_label(issuer_id: str | None) -> str:
    key = (issuer_id or DEFAULT_ISSUER).strip().lower() or DEFAULT_ISSUER
    return ISSUERS.get(key, key.replace("_", " ").title())


def can_parse(issuer_id: str | None) -> bool:
    """True if PDF statement parsing is available for this issuer."""
    key = (issuer_id or "").strip().lower()
    return key in _REGISTRY


def can_import_activity(issuer_id: str | None) -> bool:
    """CSV/Excel activity import works for any known issuer."""
    key = (issuer_id or "").strip().lower()
    return key in ISSUERS


def list_issuers(*, include_unparseable: bool = True) -> list[dict[str, Any]]:
    rows = []
    for key, label in ISSUERS.items():
        parseable = key in _REGISTRY
        if not include_unparseable and not parseable:
            continue
        rows.append(
            {
                "id": key,
                "label": label,
                "can_parse": True,  # activity CSV/Excel for all; PDF may still be Amex-only
                "can_parse_pdf": parseable,
                "can_parse_activity": True,
            }
        )
    return rows


def parse_statement(
    pdf_path: Path | str,
    *,
    filename: str | None = None,
    issuer: str | None = None,
):
    """Parse a statement PDF using the registered issuer adapter."""
    key = (issuer or DEFAULT_ISSUER).strip().lower() or DEFAULT_ISSUER
    if key not in ISSUERS:
        raise ValueError(f"Unknown issuer {key!r}. Known: {', '.join(sorted(ISSUERS))}")
    fn = _REGISTRY.get(key)
    if not fn:
        label = ISSUERS.get(key, key)
        raise ValueError(
            f"{label} PDF parsing is not available yet — only American Express is supported today."
        )
    return fn(pdf_path, filename=filename)

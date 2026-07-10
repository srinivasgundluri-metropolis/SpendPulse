"""American Express PDF adapter (thin re-export)."""

from __future__ import annotations

from pathlib import Path

from ..parser import Statement, parse_amex_pdf

ISSUER = "amex"


def parse(pdf_path: Path | str, filename: str | None = None) -> Statement:
    statement = parse_amex_pdf(pdf_path, filename=filename)
    statement.issuer = ISSUER
    return statement

#!/usr/bin/env python3
"""Replace statements.json with all statement PDFs in data/uploads."""

from __future__ import annotations

from pathlib import Path

from app.analytics import summarize_statement
from app.parsers import parse_statement
from app.storage import UPLOADS_DIR, ensure_dirs, save_all


def main() -> int:
    ensure_dirs()
    pdfs = sorted(UPLOADS_DIR.glob("*.pdf"), key=lambda p: p.name)
    if not pdfs:
        print(f"No PDFs in {UPLOADS_DIR}")
        return 1

    by_key: dict[tuple[str, str], dict] = {}
    for path in pdfs:
        print(f"Parsing {path.name}…")
        statement = parse_statement(path)
        d = statement.to_dict()
        d["stored_file"] = path.name
        d["source"] = "statement_pdf"
        d["filename"] = path.name
        # Keep latest parse if two PDFs share issuer + closing date
        by_key[(d.get("issuer") or "amex", d["closing_date"])] = d

    payload = sorted(by_key.values(), key=lambda s: s["closing_date"], reverse=True)
    save_all(payload)

    print(f"\nSaved {len(payload)} statement(s)")
    print(f"{'Period':10} {'Close':12} {'Charges':>7} {'Net':>10} {'Coffee':>8} {'Avoid':>8}")
    for s in sorted(payload, key=lambda x: x["closing_date"]):
        t = summarize_statement(s)["totals"]
        print(
            f"{s['period_label']:10} {s['closing_date']:12} "
            f"{t['transaction_count']:7} {t['net_spend']:10.2f} "
            f"{t['coffee']:8.2f} {t['avoidable']:8.2f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

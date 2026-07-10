#!/usr/bin/env python3
"""Seed the local DB from a statement PDF path."""

from __future__ import annotations

import sys
from pathlib import Path

from app.analytics import summarize_statement
from app.parsers import parse_statement
from app.storage import upsert_statement


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python seed.py /path/to/statement.pdf")
        return 1
    path = Path(sys.argv[1]).expanduser().resolve()
    if not path.exists():
        print(f"File not found: {path}")
        return 1
    statement = parse_statement(path)
    saved = upsert_statement(statement.to_dict(), source_path=path)
    summary = summarize_statement(saved)
    t = summary["totals"]
    print(f"Imported {saved['period_label']} ({saved['closing_date']})")
    print(f"  charges: {t['transaction_count']}  spend: ${t['spend']:,.2f}")
    print(f"  coffee:  {t['coffee_count']} visits  ${t['coffee']:,.2f}")
    print(f"  avoidable: ${t['avoidable']:,.2f} ({t['avoidable_share_pct']}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

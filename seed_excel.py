#!/usr/bin/env python3
"""Import Amex activity.xlsx as calendar-month statements for 2026 YTD."""

from __future__ import annotations

import argparse
from pathlib import Path

from app.excel_import import parse_activity_xlsx
from app.storage import DATA_DIR, UPLOADS_DIR, ensure_dirs, save_all


def main() -> None:
    parser = argparse.ArgumentParser(description="Import Amex activity Excel into monthly statements")
    parser.add_argument(
        "--file",
        type=Path,
        default=UPLOADS_DIR / "activity.xlsx",
        help="Path to activity.xlsx (default: data/uploads/activity.xlsx)",
    )
    parser.add_argument(
        "--replace-all",
        action="store_true",
        help="Replace entire statements.json with Excel months (default: yes for this script)",
    )
    args = parser.parse_args()
    path = args.file.expanduser().resolve()
    if not path.exists():
        raise SystemExit(f"File not found: {path}")

    ensure_dirs()
    statements = parse_activity_xlsx(path)
    if not statements:
        raise SystemExit("No transactions found in Excel file")

    payload = []
    for s in statements:
        d = s.to_dict()
        d["stored_file"] = path.name if path.parent == UPLOADS_DIR else path.name
        d["source"] = "activity_xlsx"
        payload.append(d)

    # Always replace for YTD rebuild so PDF statement periods don't collide
    save_all(payload)

    print(f"Imported {len(payload)} months from {path.name}")
    for s in sorted(payload, key=lambda x: x["closing_date"]):
        charges = sum(
            1
            for t in s["transactions"]
            if t["amount"] > 0 and not t.get("payment") and not t.get("transfer")
        )
        print(f"  {s['period_label']:8}  closing {s['closing_date']}  txs={len(s['transactions']):3}  charges≈{charges}")
    print(f"DB → {DATA_DIR / 'statements.json'}")


if __name__ == "__main__":
    main()

"""Import CSV / Excel activity exports → one statement per calendar month.

Works across issuers (Amex, Apple Card, Citi, Chase, …) by normalizing common
column aliases, then grouping by transaction month.
"""

from __future__ import annotations

import calendar
import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .categorize import build_tags, categorize
from .parser import Statement, Transaction, _fingerprint
from .reattribute import JEEVITHA, JEEVITHA_CARD, is_jeevitha_starbucks

# Canonical field → accepted header aliases (case-insensitive, stripped)
_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "date": (
        "date",
        "transaction date",
        "trans date",
        "trans. date",
        "posted date",
        "post date",
        "posting date",
        "clearing date",
        "purchase date",
        "txn date",
    ),
    "description": (
        "description",
        "merchant",
        "merchant name",
        "payee",
        "name",
        "transaction description",
        "appears on your statement as",
        "memo",
        "details",
    ),
    "amount": (
        "amount",
        "amount (usd)",
        "amount(usd)",
        "transaction amount",
        "charge amount",
        "usd amount",
        "amt",
    ),
    "debit": ("debit", "debit amount", "withdrawals", "charges"),
    "credit": ("credit", "credit amount", "deposits", "payments"),
    "cardholder": (
        "card member",
        "cardholder",
        "card holder",
        "purchased by",
        "member name",
        "account member",
        "name on card",
    ),
    "account": ("account #", "account number", "account", "card number", "last 4", "last4"),
    "type": ("type", "transaction type", "trans type", "status"),
    "category": ("category", "spending category"),
    "extended": ("extended details", "extended detail", "notes"),
    "reference": ("reference", "ref", "transaction id", "id"),
}

_PAYMENT_TYPES = re.compile(
    r"payment|pay.?ment|autopay|thank you|credit|refund|return|adjustment|interest|fee",
    re.I,
)
_CHARGE_TYPES = re.compile(r"purchase|sale|charge|debit|pending|cleared", re.I)


def _norm_header(value: object) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip().lower()
    text = text.replace("_", " ")
    return text


def _map_columns(columns: list[str]) -> dict[str, str]:
    """Return canonical → original column name."""
    norm_to_orig = {_norm_header(c): c for c in columns}
    mapped: dict[str, str] = {}
    for canon, aliases in _COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in norm_to_orig:
                mapped[canon] = norm_to_orig[alias]
                break
    return mapped


def _find_header_row(raw: pd.DataFrame) -> int:
    for i, row in raw.iterrows():
        vals = {_norm_header(v) for v in row.tolist() if pd.notna(v)}
        has_date = any(a in vals for a in _COLUMN_ALIASES["date"])
        has_amount = any(
            a in vals
            for a in _COLUMN_ALIASES["amount"] + _COLUMN_ALIASES["debit"] + _COLUMN_ALIASES["credit"]
        )
        has_desc = any(a in vals for a in _COLUMN_ALIASES["description"])
        if has_date and has_amount and has_desc:
            return int(i)
    # Fallback: first row
    return 0


def _clean_desc(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _parse_amount(value: object) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "-"}:
        return None
    neg = False
    if text.startswith("(") and text.endswith(")"):
        neg = True
        text = text[1:-1]
    text = text.replace("$", "").replace(",", "").replace("USD", "").strip()
    if text.endswith("-"):
        neg = True
        text = text[:-1].strip()
    if text.startswith("+"):
        text = text[1:]
    try:
        amt = float(text)
    except ValueError:
        return None
    return -abs(amt) if neg else amt


def _kind_for(description: str, amount: float, type_hint: str = "") -> str:
    upper = f"{description} {type_hint}".upper()
    payment_markers = (
        "MOBILE PAYMENT",
        "AUTOPAY",
        "ONLINE PAYMENT",
        "THANK YOU",
        "ELECTRONIC PAYMENT",
        "PAYMENT RECEIVED",
        "ACH PAYMENT",
        "BANK PAYMENT",
        "APPLE CARD PAYMENT",
        "PAYMENT THANK YOU",
    )
    if amount < 0 and any(p in upper for p in payment_markers):
        return "payment"
    if type_hint and _PAYMENT_TYPES.search(type_hint) and "purchase" not in type_hint.lower():
        if "fee" in type_hint.lower() or "interest" in type_hint.lower():
            return "fee"
        if "refund" in type_hint.lower() or "return" in type_hint.lower() or "credit" in type_hint.lower():
            return "credit"
        return "payment"
    if amount < 0:
        return "credit"
    if "PLAN FEE" in upper or " ANNUAL FEE" in upper:
        return "fee"
    return "charge"


def _signed_amount(raw_amount: float | None, debit: float | None, credit: float | None, type_hint: str) -> float | None:
    """Normalize to Amex-like sign: charges > 0, payments/credits < 0."""
    if debit is not None or credit is not None:
        d = abs(debit or 0.0)
        c = abs(credit or 0.0)
        if d and not c:
            return round(d, 2)
        if c and not d:
            return round(-c, 2)
        if d and c:
            return round(d - c, 2)

    if raw_amount is None:
        return None
    amt = float(raw_amount)
    hint = (type_hint or "").lower()

    # Chase-style: purchases often negative
    if hint and _CHARGE_TYPES.search(hint) and not _PAYMENT_TYPES.search(hint):
        return round(abs(amt), 2)
    if hint and _PAYMENT_TYPES.search(hint) and "purchase" not in hint:
        return round(-abs(amt), 2)

    # Already signed exports (Amex Excel, many CSVs)
    return round(amt, 2)


def _month_end(year: int, month: int) -> str:
    last = calendar.monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-{last:02d}"


def _card_ending(account: object) -> str:
    raw = str(account or "").strip()
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return ""
    return digits[-5:] if len(digits) >= 5 else digits


def _read_raw_table(path: Path) -> pd.DataFrame:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls", ".xlsm"}:
        return pd.read_excel(path, sheet_name=0, header=None)
    if suffix == ".csv":
        # Try utf-8 then latin-1; skip Apple/BOM quirks
        for enc in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                return pd.read_csv(path, header=None, dtype=str, encoding=enc, keep_default_na=False)
            except UnicodeDecodeError:
                continue
        return pd.read_csv(path, header=None, dtype=str, encoding="utf-8", errors="replace")
    raise ValueError(f"Unsupported activity file type: {suffix or path.name}")


def load_activity_frame(path: Path) -> pd.DataFrame:
    """Load CSV/Excel into a normalized frame with Date / Description / Amount / …"""
    raw = _read_raw_table(path)
    if raw.empty:
        raise ValueError("File is empty")

    header_i = _find_header_row(raw)
    header = [
        str(c).strip() if pd.notna(c) and str(c).strip() else f"col_{i}"
        for i, c in enumerate(raw.iloc[header_i].tolist())
    ]
    body = raw.iloc[header_i + 1 :].copy()
    body.columns = header
    mapped = _map_columns(header)
    if "date" not in mapped:
        raise ValueError("Could not find a Date column in this export")
    if "description" not in mapped and "extended" not in mapped:
        raise ValueError("Could not find a Description / Merchant column")
    if "amount" not in mapped and "debit" not in mapped and "credit" not in mapped:
        raise ValueError("Could not find an Amount (or Debit/Credit) column")

    rows: list[dict[str, Any]] = []
    for _, row in body.iterrows():
        date_raw = row.get(mapped["date"])
        if date_raw is None or str(date_raw).strip() == "":
            continue
        dt = pd.to_datetime(date_raw, errors="coerce")
        if pd.isna(dt):
            continue

        desc = ""
        if "description" in mapped:
            desc = _clean_desc(row.get(mapped["description"]))
        if "extended" in mapped:
            ext = _clean_desc(row.get(mapped["extended"]))
            if ext and (not desc or len(ext) > len(desc) + 5):
                # Prefer richer extended merchant line when present
                first_line = ext.splitlines()[0] if "\n" in str(row.get(mapped["extended"]) or "") else ext
                if len(first_line) >= len(desc):
                    desc = first_line or desc
        if not desc:
            continue

        type_hint = _clean_desc(row.get(mapped["type"])) if "type" in mapped else ""
        raw_amt = _parse_amount(row.get(mapped["amount"])) if "amount" in mapped else None
        debit = _parse_amount(row.get(mapped["debit"])) if "debit" in mapped else None
        credit = _parse_amount(row.get(mapped["credit"])) if "credit" in mapped else None
        amount = _signed_amount(raw_amt, debit, credit, type_hint)
        if amount is None or amount == 0:
            continue

        cardholder = (
            _clean_desc(row.get(mapped["cardholder"])) if "cardholder" in mapped else ""
        ) or "Primary"
        account = row.get(mapped["account"]) if "account" in mapped else ""
        reference = _clean_desc(row.get(mapped["reference"])) if "reference" in mapped else ""

        rows.append(
            {
                "Date": dt.to_pydatetime() if hasattr(dt, "to_pydatetime") else dt,
                "Description": desc,
                "Amount": amount,
                "Cardholder": cardholder,
                "Account": account,
                "Type": type_hint,
                "Reference": reference,
            }
        )

    if not rows:
        raise ValueError("No transactions found after reading the file")

    df = pd.DataFrame(rows).sort_values("Date")
    return df


def rows_to_transactions(month_df: pd.DataFrame) -> list[Transaction]:
    txs: list[Transaction] = []
    seen: set[str] = set()
    for _, row in month_df.iterrows():
        date = row["Date"].strftime("%Y-%m-%d")
        description = _clean_desc(row["Description"])
        amount = round(float(row["Amount"]), 2)
        cardholder = _clean_desc(row.get("Cardholder")) or "Primary"
        card_ending = _card_ending(row.get("Account"))
        type_hint = _clean_desc(row.get("Type"))

        if is_jeevitha_starbucks(description):
            cardholder = JEEVITHA
            card_ending = JEEVITHA_CARD or card_ending

        kind = _kind_for(description, amount, type_hint)
        cats = categorize(description, amount)
        payment = cats["payment"] or kind == "payment"
        credit = cats["credit"] or kind == "credit" or (amount < 0 and not payment)
        fp = _fingerprint(date, description, amount, cardholder)
        if fp in seen:
            ref = _clean_desc(row.get("Reference"))
            fp = _fingerprint(date, f"{description}|{ref}|{type_hint}", amount, cardholder)
            if fp in seen:
                continue
        seen.add(fp)

        final_kind = "payment" if payment else ("credit" if credit and amount < 0 else kind)
        tags = build_tags(
            cats["category"],
            description=description,
            coffee=bool(cats["coffee"]),
            avoidable=bool(cats["avoidable"]),
            company_expense=bool(cats.get("company_expense")),
            transfer=bool(cats["transfer"]),
            payment=payment,
            credit=credit,
            kind=final_kind,
        )
        txs.append(
            Transaction(
                date=date,
                description=description,
                amount=amount,
                cardholder=cardholder,
                card_ending=card_ending,
                category=cats["category"],
                avoidable=cats["avoidable"],
                coffee=cats["coffee"],
                transfer=cats["transfer"],
                payment=payment,
                credit=credit,
                company_expense=bool(cats.get("company_expense")),
                kind=final_kind,
                fingerprint=fp,
                tags=tags,
            )
        )
    return txs


def parse_activity_file(path: Path | str, *, issuer: str = "amex") -> list[Statement]:
    """Split an activity CSV/Excel into one statement per calendar month for `issuer`."""
    path = Path(path)
    issuer_key = (issuer or "amex").strip().lower() or "amex"
    df = load_activity_frame(path)
    uploaded_at = datetime.now().isoformat(timespec="seconds")
    statements: list[Statement] = []

    for (year, month), month_df in df.groupby([df["Date"].dt.year, df["Date"].dt.month]):
        year_i, month_i = int(year), int(month)
        txs = rows_to_transactions(month_df)
        if not txs:
            continue
        last_txn = max(t.date for t in txs)
        month_end = _month_end(year_i, month_i)
        closing_date = min(last_txn, month_end)
        period_label = datetime(year_i, month_i, 1).strftime("%b %Y")
        period_start = min(t.date for t in txs)
        period_end = last_txn
        file_label = f"{issuer_key}_activity_{year_i:04d}-{month_i:02d}{path.suffix.lower()}"
        statement_id = hashlib.sha1(
            f"activity|{issuer_key}|{closing_date}|{period_label}|{len(txs)}|{path.name}".encode()
        ).hexdigest()[:12]
        endings = {t.card_ending for t in txs if t.card_ending}
        account_ending = next(iter(endings), None)

        statements.append(
            Statement(
                id=statement_id,
                filename=file_label,
                closing_date=closing_date,
                period_label=period_label,
                period_start=period_start,
                period_end=period_end,
                new_balance=None,
                minimum_due=None,
                payment_due_date=None,
                account_ending=account_ending,
                uploaded_at=uploaded_at,
                issuer=issuer_key,
                transactions=txs,
            )
        )

    statements.sort(key=lambda s: s.closing_date, reverse=True)
    return statements

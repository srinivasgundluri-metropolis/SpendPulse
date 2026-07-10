"""Parse Amex activity Excel exports into calendar-month statements."""

from __future__ import annotations

import calendar
import hashlib
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

from .categorize import categorize
from .parser import Statement, Transaction, _fingerprint
from .reattribute import JEEVITHA, JEEVITHA_CARD, is_jeevitha_starbucks

HEADER_MARKERS = {"Date", "Description", "Amount", "Card Member"}


def _find_header_row(raw: pd.DataFrame) -> int:
    for i, row in raw.iterrows():
        vals = {str(v).strip() for v in row.tolist() if pd.notna(v)}
        if HEADER_MARKERS.issubset(vals):
            return int(i)
    raise ValueError("Could not find transaction header row (Date / Description / Amount)")


def _clean_desc(value: object) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text


def _looks_truncated(text: str) -> bool:
    """Excel often glues truncated merchant + city: STOCHICAGO, JOURCHICAGO, CChicago."""
    if not text:
        return True
    return bool(
        re.search(
            r"(STO|JOUR|AND|COFFEE|CAFE|DISCOURS|FAIRGROUNDS)\s*[A-Z]?CHICAGO|"
            r"[A-Z]C[Hh]icago|"
            r"WOOD STREET C|"
            r"STARBUCKS STO[^R]",
            text,
            re.I,
        )
    )


def _best_description(row: pd.Series) -> str:
    """Prefer Extended Details merchant lines — Excel Description is often truncated."""
    appears = _clean_desc(row.get("Appears On Your Statement As"))
    desc = _clean_desc(row.get("Description"))
    primary = appears or desc
    extended = str(row.get("Extended Details") or "")
    ext_upper = extended.upper()

    candidates: list[tuple[int, str]] = []
    for line in extended.splitlines():
        line = _clean_desc(line)
        if not line:
            continue
        low = line.lower()
        if low.startswith(("description", "price :", "price:")):
            continue
        upper = line.upper()
        score = len(line)
        if "GIFT CARD" in upper:
            score += 200  # beat bare STARBUCKS line
        if any(
            k in upper
            for k in (
                "APLPAY",
                "STARBUCKS STORE",
                "DUNKIN",
                "TOUS LES",
                "FAIRGROUNDS",
                "MOKA",
                "DISCOURSE",
                "WOOD STREET",
                "TST*",
                "COFFEE",
                "CAFE",
                "CAFÉ",
            )
        ):
            score += 120
        elif "STARBUCKS" in upper:
            score += 40
        if "squareup" in low or "receipts" in low or "@" in line:
            score -= 40
        if re.fullmatch(r"[A-Z0-9]{10,}", upper.replace(" ", "")):
            score -= 60
        candidates.append((score, line))

    best_ext = ""
    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        best_ext = candidates[0][1]

    # Preserve gift-card signal even if another line scored higher
    if "GIFT CARD" in ext_upper and "STARBUCKS" in ext_upper:
        gift_line = next((ln for _, ln in candidates if "GIFT CARD" in ln.upper()), "")
        if gift_line:
            return f"STARBUCKS GIFT CARD {gift_line}"

    if best_ext and (not primary or _looks_truncated(primary) or len(best_ext) >= len(primary) - 2):
        return best_ext
    return primary or best_ext or "Unknown"


def _card_ending(account: object) -> str:
    raw = str(account or "").strip()
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return ""
    return f"{digits[-5:]}" if len(digits) >= 5 else digits


def _kind_for(description: str, amount: float) -> str:
    upper = description.upper()
    payment_markers = (
        "MOBILE PAYMENT",
        "AUTOPAY",
        "ONLINE PAYMENT",
        "THANK YOU",
        "ELECTRONIC PAYMENT",
        "PAYMENT RECEIVED",
        "ACH PAYMENT",
        "BANK PAYMENT",
    )
    if amount < 0 and any(p in upper for p in payment_markers):
        return "payment"
    if amount < 0:
        return "credit"
    if "PLAN FEE" in upper or " ANNUAL FEE" in upper:
        return "fee"
    if "ADJ " in upper or "ADJUSTMENT" in upper:
        return "fee"
    return "charge"


def _month_end(year: int, month: int) -> str:
    last = calendar.monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-{last:02d}"


def load_activity_rows(path: Path) -> pd.DataFrame:
    raw = pd.read_excel(path, sheet_name=0, header=None)
    header_i = _find_header_row(raw)
    header = [str(c).strip() if pd.notna(c) else f"col_{i}" for i, c in enumerate(raw.iloc[header_i].tolist())]
    body = raw.iloc[header_i + 1 :].copy()
    body.columns = header
    body = body.dropna(subset=["Date"])
    body["Date"] = pd.to_datetime(body["Date"], errors="coerce")
    body = body.dropna(subset=["Date"])
    body["Amount"] = pd.to_numeric(body["Amount"], errors="coerce")
    body = body.dropna(subset=["Amount"])
    return body.sort_values("Date")


def rows_to_transactions(month_df: pd.DataFrame) -> list[Transaction]:
    txs: list[Transaction] = []
    seen: set[str] = set()
    for _, row in month_df.iterrows():
        date = row["Date"].strftime("%Y-%m-%d")
        description = _best_description(row)
        amount = round(float(row["Amount"]), 2)
        cardholder = _clean_desc(row.get("Card Member")) or "Unknown"
        card_ending = _card_ending(row.get("Account #"))
        if is_jeevitha_starbucks(description):
            cardholder = JEEVITHA
            card_ending = JEEVITHA_CARD or card_ending

        kind = _kind_for(description, amount)
        # Categorizer expects signed amount for credits
        cats = categorize(description, amount)
        payment = cats["payment"] or kind == "payment"
        credit = cats["credit"] or kind == "credit" or amount < 0
        fp = _fingerprint(date, description, amount, cardholder)
        if fp in seen:
            # Same-day duplicates: include reference if present
            ref = _clean_desc(row.get("Reference"))
            fp = _fingerprint(date, f"{description}|{ref}", amount, cardholder)
            if fp in seen:
                continue
        seen.add(fp)

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
                kind="payment" if payment else ("credit" if credit and amount < 0 else kind),
                fingerprint=fp,
            )
        )
    return txs


def parse_activity_xlsx(path: Path) -> list[Statement]:
    """Backward-compatible Amex Excel import → monthly statements."""
    from .activity_import import parse_activity_file

    return parse_activity_file(path, issuer="amex")

"""Parse American Express PDF statements into structured transactions."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from pypdf import PdfReader

from .categorize import build_tags, categorize
from .reattribute import JEEVITHA, JEEVITHA_CARD, is_jeevitha_starbucks

DATE_RE = re.compile(r"^(\d{2}/\d{2}/\d{2})\*?\s+(.+)$")
ARRIVAL_PAIR_RE = re.compile(r"^\d{2}/\d{2}/\d{2}\s+\d{2}/\d{2}/\d{2}$")
AMOUNT_RE = re.compile(r"^\$([\d,]+\.\d{2})\s*[⧫♦]?\s*$")
NEG_AMOUNT_RE = re.compile(r"^-?\$([\d,]+\.\d{2})\s*[⧫♦]?\s*$")
CLOSING_RE = re.compile(r"Closing Date\s+(\d{2}/\d{2}/\d{2})")
NEW_BALANCE_RE = re.compile(r"New Balance\s+\$([\d,]+\.\d{2})")
MIN_DUE_RE = re.compile(r"Minimum Payment Due\s+\$([\d,]+\.\d{2})")
DUE_DATE_RE = re.compile(r"Payment Due Date\s+(\d{2}/\d{2}/\d{2})")
ACCOUNT_RE = re.compile(r"Account Ending\s+([\d-]+)")
CARD_ENDING_RE = re.compile(r"Card Ending\s+([\d-]+)")
# Membership Rewards® Points\nAvailable and Pending as of MM/DD/YY\n  18,298
REWARDS_POINTS_RE = re.compile(
    r"Membership Rewards[^\n]*Points\s*"
    r"Available and Pending as of\s+(\d{2}/\d{2}/\d{2})\s*"
    r"([\d,]+)",
    re.IGNORECASE,
)

SKIP_LINE_PREFIXES = (
    "p.",
    "continued",
    "detail",
    "summary",
    "foreign",
    "spend amount",
    "amount",
    "pay in full",
    "pay over time",
    "plan balance",
    "total new charges",
    "total payments",
    "about trailing",
    "you may see interest",
    "trailing interest",
    "fees - plan",
    "interest charged",
    "total fees",
    "total interest",
    "platinum card",
    "see page",
    "customer care",
    "arrival date",
    "created",
    "description duration",
    "2026 fees",
    "fees and interest",
    "interest charge calculation",
    "information on pay over time",
    "important notices",
)


@dataclass
class Transaction:
    date: str
    description: str
    amount: float
    cardholder: str
    card_ending: str
    category: str
    avoidable: bool
    coffee: bool
    transfer: bool
    payment: bool
    credit: bool
    company_expense: bool
    kind: str  # charge | payment | credit | fee
    fingerprint: str
    tags: list[str] = field(default_factory=list)


@dataclass
class Statement:
    id: str
    filename: str
    closing_date: str
    period_label: str
    new_balance: float | None
    minimum_due: float | None
    payment_due_date: str | None
    account_ending: str | None
    uploaded_at: str
    rewards_points: int | None = None
    rewards_as_of: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    issuer: str = "amex"
    transactions: list[Transaction] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "filename": self.filename,
            "issuer": self.issuer or "amex",
            "closing_date": self.closing_date,
            "period_label": self.period_label,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "new_balance": self.new_balance,
            "minimum_due": self.minimum_due,
            "payment_due_date": self.payment_due_date,
            "account_ending": self.account_ending,
            "uploaded_at": self.uploaded_at,
            "rewards_points": self.rewards_points,
            "rewards_as_of": self.rewards_as_of,
            "transactions": [asdict(t) for t in self.transactions],
        }


def _money(value: str) -> float:
    return float(value.replace(",", ""))


def _parse_date(mmddyy: str) -> str:
    dt = datetime.strptime(mmddyy, "%m/%d/%y")
    return dt.strftime("%Y-%m-%d")


def _spend_period(
    transactions: list[Transaction], closing_date: str
) -> tuple[str, str | None, str | None]:
    """Label by primary spend month (statement closes after that month).

    Amex cycles close early next month — e.g. June spend lands on the Jul 7
    statement — so period_label is the majority charge month, not closing month.
    """
    charges = [
        t
        for t in transactions
        if t.amount > 0 and not t.payment and not t.transfer and t.kind not in {"payment", "fee"}
    ]
    if charges:
        dates = sorted(t.date for t in charges)
        period_start, period_end = dates[0], dates[-1]
        primary = Counter(d[:7] for d in dates).most_common(1)[0][0]
        y, m = map(int, primary.split("-"))
        return datetime(y, m, 1).strftime("%b %Y"), period_start, period_end

    # No charges: fall back to calendar month before closing date
    close = datetime.strptime(closing_date, "%Y-%m-%d")
    year, month = (close.year, close.month - 1) if close.month > 1 else (close.year - 1, 12)
    return datetime(year, month, 1).strftime("%b %Y"), None, None


def _parse_rewards(text: str) -> tuple[int | None, str | None]:
    """Return (available+pending points, as-of ISO date) from statement summary."""
    cleaned = text.replace("\xa0", " ")
    m = REWARDS_POINTS_RE.search(cleaned)
    if not m:
        return None, None
    as_of = _parse_date(m.group(1))
    points = int(m.group(2).replace(",", "").strip())
    return points, as_of


def _should_skip(line: str) -> bool:
    low = line.lower().strip()
    if not low:
        return True
    return any(low.startswith(p) for p in SKIP_LINE_PREFIXES)


def _fingerprint(date: str, description: str, amount: float, cardholder: str) -> str:
    raw = f"{date}|{description}|{amount:.2f}|{cardholder}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _extract_text(pdf_path: Path) -> str:
    reader = PdfReader(str(pdf_path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _detect_section(line: str, current: str) -> str:
    low = line.lower().strip()
    if low.startswith("plan balance details") or low.startswith("interest charge calculation"):
        return "done"
    if low.startswith("2026 fees and interest") or low.startswith("fees and interest totals"):
        return "done"
    if low.startswith("important notices"):
        return "done"
    if "new charges" in low and "summary" not in low:
        return "charges"
    if low.startswith("payments and credits") or low == "payments" or low.startswith("credits"):
        if "summary" in low:
            return current
        if low.startswith("payments and credits"):
            return "payments_credits"
        if low == "payments":
            return "payments"
        if low.startswith("credits"):
            return "credits"
    if low.startswith("fees"):
        return "fees"
    if "interest charged" in low:
        return "interest"
    return current


def _looks_like_cardholder_header(line: str, next_line: str | None) -> bool:
    if CARD_ENDING_RE.search(line):
        return False
    if DATE_RE.match(line):
        return False
    if AMOUNT_RE.match(line) or NEG_AMOUNT_RE.match(line):
        return False
    if next_line and CARD_ENDING_RE.search(next_line):
        return True
    # Names often appear alone before "Card Ending"
    words = line.split()
    if 1 <= len(words) <= 4 and line == line.title() or line.isupper():
        if not any(ch.isdigit() for ch in line) and "$" not in line:
            return len(line) > 2 and not _should_skip(line)
    return False


def parse_amex_pdf(pdf_path: Path | str, filename: str | None = None) -> Statement:
    path = Path(pdf_path)
    text = _extract_text(path)
    lines = [ln.strip() for ln in text.splitlines()]

    closing_raw = CLOSING_RE.search(text)
    if not closing_raw:
        raise ValueError("Could not find Closing Date in this PDF. Is it an Amex statement?")
    closing_date = _parse_date(closing_raw.group(1))

    new_balance_m = NEW_BALANCE_RE.search(text)
    min_due_m = MIN_DUE_RE.search(text)
    due_date_m = DUE_DATE_RE.search(text)
    account_m = ACCOUNT_RE.search(text)
    rewards_points, rewards_as_of = _parse_rewards(text)

    file_label = filename or path.name
    statement_id = hashlib.sha1(f"{closing_date}|{file_label}|{len(text)}".encode()).hexdigest()[:12]

    transactions: list[Transaction] = []
    section = "preamble"
    cardholder = "Primary"
    card_ending = account_m.group(1) if account_m else ""

    i = 0
    while i < len(lines):
        line = lines[i]
        next_line = lines[i + 1] if i + 1 < len(lines) else None
        section = _detect_section(line, section)
        if section == "done":
            break

        card_m = CARD_ENDING_RE.search(line)
        if card_m:
            card_ending = card_m.group(1)
            i += 1
            continue

        # Cardholder name just above "Card Ending ..."
        if next_line and CARD_ENDING_RE.search(next_line) and not DATE_RE.match(line):
            if line and not _should_skip(line) and "Account Ending" not in line:
                cardholder = line
                i += 1
                continue

        # Hotel stay arrival/departure pairs are not transactions
        if ARRIVAL_PAIR_RE.match(line):
            i += 1
            continue

        date_m = DATE_RE.match(line)
        if not date_m:
            i += 1
            continue

        # Only parse activity in relevant sections; also allow once New Charges starts
        if section not in {"payments", "credits", "payments_credits", "charges", "fees"}:
            # Some statements put charges without a clean header catch — accept after first New Charges
            if "New Charges" not in "\n".join(lines[: i + 1]):
                i += 1
                continue
            section = "charges"

        date_raw, rest = date_m.group(1), date_m.group(2).strip()
        desc_parts: list[str] = []
        amount = None
        j = i + 1

        # Amount sometimes sits on the same line: "06/20/26* NAME MOBILE PAYMENT -$1,200.00"
        same_line_amt = re.search(r"(-?)\$([\d,]+\.\d{2})\s*[⧫♦]?\s*$", rest)
        if same_line_amt:
            sign, raw_amt = same_line_amt.group(1), same_line_amt.group(2)
            amount = -_money(raw_amt) if sign == "-" else _money(raw_amt)
            rest = rest[: same_line_amt.start()].strip()
            desc_parts.append(rest)
        else:
            desc_parts.append(rest)

        while amount is None and j < len(lines):
            candidate = lines[j]
            if DATE_RE.match(candidate) and not ARRIVAL_PAIR_RE.match(candidate):
                # A real next transaction — stop. Arrival/departure pairs are skipped below.
                break
            if ARRIVAL_PAIR_RE.match(candidate):
                j += 1
                continue
            # End of charge block: summary / next card section
            if "Account Ending" in candidate and not candidate.upper().startswith(
                ("DATE", "AMOUNT")
            ):
                # e.g. "NAME Account Ending 1234" footer lines
                if re.search(r"Account Ending\s+[\d-]+", candidate):
                    break
            if candidate.startswith("Platinum Card"):
                break
            if CARD_ENDING_RE.search(candidate):
                break
            if (
                j + 1 < len(lines)
                and CARD_ENDING_RE.search(lines[j + 1])
                and not AMOUNT_RE.match(candidate)
                and not NEG_AMOUNT_RE.match(candidate)
            ):
                break

            amt_m = NEG_AMOUNT_RE.match(candidate) or AMOUNT_RE.match(candidate)
            if amt_m and ("$" in candidate):
                amount = (
                    -_money(amt_m.group(1))
                    if candidate.strip().startswith("-")
                    else _money(amt_m.group(1))
                )
                j += 1
                break

            if _should_skip(candidate):
                j += 1
                continue
            if re.match(r"^[\d,]+\.\d{2}$", candidate):
                j += 1
                continue
            if re.search(r"Rupees|Dollars|Euro|Yen|Pounds", candidate, re.I):
                j += 1
                continue
            if candidate in {"LODGING", "CLOTHING", "MERCHANDISE"}:
                desc_parts.append(candidate)
                j += 1
                continue
            if len(candidate) > 1:
                desc_parts.append(candidate)
            j += 1

        if amount is None:
            i += 1
            continue

        description = " ".join(p for p in desc_parts if p).strip()
        description = re.sub(r"\s+", " ", description)

        # Normalize sign by section
        kind = "charge"
        if section in {"payments", "payments_credits"} and "PAYMENT" in description.upper():
            kind = "payment"
            amount = -abs(amount)
        elif section in {"credits", "payments_credits"} or amount < 0:
            if "PAYMENT" in description.upper():
                kind = "payment"
                amount = -abs(amount)
            else:
                kind = "credit"
                amount = -abs(amount)
        elif section == "fees":
            kind = "fee"
            amount = abs(amount)
        else:
            kind = "charge"
            amount = abs(amount)

        # Explicit debit adjustments are charges
        if "DEBIT ADJUSTMENT" in description.upper():
            kind = "charge"
            amount = abs(amount)

        cats = categorize(description, amount)
        # UIC-area Starbucks + Starbucks gift cards → Jeevitha (even if charged on primary)
        tx_cardholder = cardholder
        tx_card_ending = card_ending
        if is_jeevitha_starbucks(description):
            tx_cardholder = JEEVITHA
            tx_card_ending = JEEVITHA_CARD or card_ending
        tx = Transaction(
            date=_parse_date(date_raw),
            description=description,
            amount=round(amount, 2),
            cardholder=tx_cardholder,
            card_ending=tx_card_ending,
            category=cats["category"],
            avoidable=cats["avoidable"],
            coffee=cats["coffee"],
            transfer=cats["transfer"],
            payment=cats["payment"] or kind == "payment",
            credit=cats["credit"] or kind == "credit",
            company_expense=bool(cats.get("company_expense")),
            kind=kind,
            fingerprint=_fingerprint(
                _parse_date(date_raw), description, round(amount, 2), tx_cardholder
            ),
            tags=build_tags(
                cats["category"],
                description=description,
                coffee=bool(cats["coffee"]),
                avoidable=bool(cats["avoidable"]),
                company_expense=bool(cats.get("company_expense")),
                transfer=bool(cats["transfer"]),
                payment=bool(cats["payment"] or kind == "payment"),
                credit=bool(cats["credit"] or kind == "credit"),
                kind=kind,
            ),
        )
        transactions.append(tx)
        i = j

    # Deduplicate exact fingerprints within statement
    seen: set[str] = set()
    unique: list[Transaction] = []
    for tx in transactions:
        if tx.fingerprint in seen:
            continue
        seen.add(tx.fingerprint)
        unique.append(tx)

    period_label, period_start, period_end = _spend_period(unique, closing_date)

    return Statement(
        id=statement_id,
        filename=file_label,
        closing_date=closing_date,
        period_label=period_label,
        period_start=period_start,
        period_end=period_end,
        new_balance=_money(new_balance_m.group(1)) if new_balance_m else None,
        minimum_due=_money(min_due_m.group(1)) if min_due_m else None,
        payment_due_date=_parse_date(due_date_m.group(1)) if due_date_m else None,
        account_ending=account_m.group(1) if account_m else None,
        uploaded_at=datetime.now().isoformat(timespec="seconds"),
        rewards_points=rewards_points,
        rewards_as_of=rewards_as_of,
        issuer="amex",
        transactions=unique,
    )

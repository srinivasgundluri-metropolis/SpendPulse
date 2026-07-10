"""Aggregate spending insights from parsed statements."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from typing import Any

from .dining import dining_breakdown

_STOP_TOKENS = {
    "APL",
    "APLPAY",
    "PAY",
    "TST",
    "THE",
    "AND",
    "FOR",
    "WITH",
    "FROM",
    "CREDIT",
    "CREDITS",
    "REFUND",
    "PLATINUM",
    "BENEFIT",
    "GOODWILL",
    "OFFER",
    "AMEX",
    "MEMBER",
    "STORE",
    "ONLINE",
    "HELP",
    "COM",
    "BILL",
    "USA",
    "LLC",
    "INC",
    "CHICAGO",
    "IL",
    "CA",
    "NY",
    "WA",
    "TX",
    "FL",
    "AR",
    "CO",
    "MD",
    "TN",
    "SC",
    "IN",
    "PROMOTIONAL",
    "ADJUSTMENT",
    "DEBIT",
    "THANK",
    "YOU",
}


def _is_transfer(t: dict) -> bool:
    """Card-linked transfers (Add Money / Transfer to Card / plan fees) — not spend."""
    if t.get("transfer"):
        return True
    cat = (t.get("category") or "").strip()
    if cat in {"Transfers", "Amex Send"}:
        return True
    desc = (t.get("description") or "").upper()
    return "AMEX SEND" in desc or "ADD MONEY" in desc or "TRANSFER TO CARD" in desc


def _is_amex_send(t: dict) -> bool:
    """Backward-compatible alias for _is_transfer."""
    return _is_transfer(t)


def _spend_txs(transactions: list[dict]) -> list[dict]:
    return [
        t
        for t in transactions
        if t["amount"] > 0
        and not t.get("payment")
        and not _is_transfer(t)
        and t.get("kind") not in {"payment", "fee"}
    ]


def _refund_txs(transactions: list[dict]) -> list[dict]:
    """True refunds / statement credits — not payments or card transfers."""
    refunds = []
    for t in transactions:
        if t.get("payment") or t.get("kind") == "payment":
            continue
        if _is_transfer(t):
            continue
        if t.get("kind") == "fee":
            continue
        if t["amount"] >= 0 and t.get("kind") != "credit":
            continue
        # Prefer negative amounts; also keep explicit credit kind
        if t["amount"] < 0 or t.get("kind") == "credit" or t.get("credit"):
            if t["amount"] == 0:
                continue
            refunds.append(t)
    return refunds


def _transfer_txs(transactions: list[dict]) -> list[dict]:
    return [t for t in transactions if _is_transfer(t)]


def _amex_send_txs(transactions: list[dict]) -> list[dict]:
    return _transfer_txs(transactions)


def _tokens(text: str) -> set[str]:
    parts = re.findall(r"[A-Z0-9]{3,}", (text or "").upper())
    return {p for p in parts if p not in _STOP_TOKENS and not p.isdigit()}


def _match_score(refund: dict, charge: dict) -> int:
    """Higher is better. 0 = no merchant link (do not wash on amount alone)."""
    r_desc = refund.get("description") or ""
    c_desc = charge.get("description") or ""
    r_tok = _tokens(r_desc)
    c_tok = _tokens(c_desc)
    overlap = r_tok & c_tok
    score = len(overlap) * 10

    # Strong brand / merchant hints even if tokenized oddly
    pairs = (
        ("HOTEL", "HOTEL"),
        ("LODGING", "LODGING"),
        ("UBER ONE", "UBER ONE"),
        ("HULU", "HULU"),
        ("HLU", "HULU"),
        ("WALMART+", "WALMART+"),
        ("LULULEMON", "LULULEMON"),
        ("PLANTA", "PLANTA"),
        ("GROUPON", "GROUPON"),
        ("RESY", "PLANTA"),
        ("ADJUSTMENT", "ADJUSTMENT"),
    )
    ru, cu = r_desc.upper(), c_desc.upper()
    for a, b in pairs:
        if a in ru and b in cu:
            score += 20

    # Same cardholder preferred
    if (refund.get("cardholder") or "").strip().lower() == (
        charge.get("cardholder") or ""
    ).strip().lower():
        score += 2

    return score


def _wash_exact_refunds(
    spend: list[dict], refunds: list[dict]
) -> tuple[list[dict], list[dict], list[dict]]:
    """
    If a refund amount exactly matches a charge and they share merchant signal,
    drop both from spend/refund totals (fully washed). Return washed pair records.
    """
    remaining_spend = list(spend)
    remaining_refunds: list[dict] = []
    washed: list[dict] = []

    # Match refunds to best charge candidate; one charge per refund
    used_charge_idx: set[int] = set()

    for refund in refunds:
        amt = round(abs(float(refund["amount"])), 2)
        best_i = None
        best_score = 0
        for i, charge in enumerate(remaining_spend):
            if i in used_charge_idx:
                continue
            if round(float(charge["amount"]), 2) != amt:
                continue
            score = _match_score(refund, charge)
            if score > best_score:
                best_score = score
                best_i = i
        # Require a real merchant link (score >= 10 from one token or brand pair)
        if best_i is not None and best_score >= 10:
            charge = remaining_spend[best_i]
            used_charge_idx.add(best_i)
            washed.append(
                {
                    "amount": amt,
                    "charge": charge,
                    "refund": refund,
                    "description": charge.get("description") or refund.get("description"),
                    "cardholder": charge.get("cardholder") or refund.get("cardholder"),
                    "date": charge.get("date") or refund.get("date"),
                    "category": charge.get("category") or "Washed",
                }
            )
        else:
            remaining_refunds.append(refund)

    kept_spend = [c for i, c in enumerate(remaining_spend) if i not in used_charge_idx]
    return kept_spend, remaining_refunds, washed


def _refund_type(description: str) -> str:
    upper = description.upper()
    if "PLATINUM" in upper and "CREDIT" in upper:
        return "Card benefit"
    if "AMEX OFFER" in upper or "OFFER CREDIT" in upper:
        return "Issuer offer"
    if "GOODWILL" in upper or "SAKS BENEFIT" in upper:
        return "Card benefit"
    if "HOTEL" in upper or "LODGING" in upper or "AMEXTRAVEL" in upper:
        return "Travel credit"
    if "REFUND" in upper or "TO C" in upper:
        return "Merchant refund"
    if "ADJUSTMENT" in upper:
        return "Adjustment"
    if "CREDIT" in upper:
        return "Statement credit"
    return "Refund / credit"


def _filter_cardholder(transactions: list[dict], cardholder: str | None) -> list[dict]:
    if not cardholder or cardholder in {"", "all", "All members"}:
        return transactions
    target = cardholder.strip().lower()
    return [t for t in transactions if (t.get("cardholder") or "").strip().lower() == target]


def _tx_tags(t: dict) -> list[str]:
    tags = t.get("tags")
    if isinstance(tags, list) and tags:
        return [str(x) for x in tags]
    cat = (t.get("category") or "Misc").strip() or "Misc"
    return [cat]


def _filter_tag(transactions: list[dict], tag: str | None) -> list[dict]:
    if not tag or tag in {"", "all", "All tags"}:
        return transactions
    target = tag.strip().lower()
    return [
        t
        for t in transactions
        if any(str(x).strip().lower() == target for x in _tx_tags(t))
    ]


def _collect_tags(transactions: list[dict]) -> list[str]:
    seen: set[str] = set()
    for t in transactions:
        for tag in _tx_tags(t):
            if tag:
                seen.add(tag)
    # Brand filters first (easy to find), then categories, then other meta tags
    brands = ("Starbucks", "Tesla")
    meta = {"Coffee", "Avoidable", "Company", "Transfers", "Amex Send", "Payment", "Credit", "Tesla", "Starbucks"}
    brand_list = [t for t in brands if t in seen]
    cats = sorted(t for t in seen if t not in meta)
    extras = sorted(t for t in seen if t in meta and t not in brands)
    return brand_list + cats + extras


def summarize_statement(
    statement: dict, cardholder: str | None = None, tag: str | None = None
) -> dict[str, Any]:
    txs = _filter_tag(_filter_cardholder(statement["transactions"], cardholder), tag)
    raw_spend = _spend_txs(txs)
    raw_refunds = _refund_txs(txs)
    spend_all, refunds, washed = _wash_exact_refunds(raw_spend, raw_refunds)
    company = [t for t in spend_all if t.get("company_expense")]
    # Personal spend excludes company-expensed charges (e.g. Metropolis parking)
    spend = [t for t in spend_all if not t.get("company_expense")]
    coffee = [t for t in spend if t.get("coffee")]
    avoidable = [t for t in spend if t.get("avoidable")]
    transport = [t for t in spend if t.get("category") == "Transport"]
    ev_charging = [t for t in spend if t.get("category") == "EV Charging"]
    tesla_insurance = [t for t in spend if t.get("category") == "Tesla Insurance"]
    tesla_fsd = [t for t in spend if t.get("category") == "Tesla FSD"]
    tesla_other = [t for t in spend if t.get("category") == "Tesla"]
    tesla_all = ev_charging + tesla_insurance + tesla_fsd + tesla_other
    payments = [t for t in txs if t.get("payment") or t.get("kind") == "payment"]

    # Member list always from full statement (for filter dropdown)
    all_holders = sorted(
        {
            (t.get("cardholder") or "").strip()
            for t in statement["transactions"]
            if (t.get("cardholder") or "").strip()
            and t["amount"] > 0
            and not t.get("payment")
            and not _is_transfer(t)
            and t.get("kind") not in {"payment", "fee"}
        }
    )

    transfers = _transfer_txs(txs)
    transfer_in = sum(t["amount"] for t in transfers if t["amount"] > 0)
    transfer_out = sum(abs(t["amount"]) for t in transfers if t["amount"] < 0)

    by_category: dict[str, float] = defaultdict(float)
    by_day: dict[str, float] = defaultdict(float)
    coffee_by_merchant: dict[str, dict[str, float | int]] = {}
    avoidable_by_category: dict[str, float] = defaultdict(float)
    merchant_totals: dict[str, dict[str, float | int | str]] = {}
    refunds_by_type: dict[str, float] = defaultdict(float)
    by_cardholder: dict[str, dict[str, float | int | str]] = {}

    for t in spend:
        by_category[t["category"]] += t["amount"]
        by_day[t["date"]] += t["amount"]

        holder = (t.get("cardholder") or "Unknown").strip() or "Unknown"
        if holder not in by_cardholder:
            by_cardholder[holder] = {
                "cardholder": holder,
                "card_ending": t.get("card_ending") or "",
                "total": 0.0,
                "count": 0,
                "coffee": 0.0,
                "coffee_count": 0,
                "avoidable": 0.0,
                "avoidable_count": 0,
            }
        row = by_cardholder[holder]
        if t.get("card_ending") and not row["card_ending"]:
            row["card_ending"] = t["card_ending"]
        row["total"] = float(row["total"]) + t["amount"]
        row["count"] = int(row["count"]) + 1
        if t.get("coffee"):
            row["coffee"] = float(row["coffee"]) + t["amount"]
            row["coffee_count"] = int(row["coffee_count"]) + 1
        if t.get("avoidable"):
            row["avoidable"] = float(row["avoidable"]) + t["amount"]
            row["avoidable_count"] = int(row["avoidable_count"]) + 1

        merchant = t["description"][:60]
        if merchant not in merchant_totals:
            merchant_totals[merchant] = {
                "merchant": merchant,
                "total": 0.0,
                "count": 0,
                "category": t["category"],
                "avoidable": t.get("avoidable", False),
                "coffee": t.get("coffee", False),
            }
        merchant_totals[merchant]["total"] = float(merchant_totals[merchant]["total"]) + t["amount"]
        merchant_totals[merchant]["count"] = int(merchant_totals[merchant]["count"]) + 1

        if t.get("coffee"):
            key = _coffee_merchant_key(t["description"])
            if key not in coffee_by_merchant:
                coffee_by_merchant[key] = {"merchant": key, "total": 0.0, "count": 0}
            coffee_by_merchant[key]["total"] = float(coffee_by_merchant[key]["total"]) + t["amount"]
            coffee_by_merchant[key]["count"] = int(coffee_by_merchant[key]["count"]) + 1

        if t.get("avoidable"):
            avoidable_by_category[t["category"]] += t["amount"]

    refund_rows = []
    for t in refunds:
        rtype = _refund_type(t["description"])
        amt = abs(t["amount"])
        refunds_by_type[rtype] += amt
        refund_rows.append({**t, "refund_type": rtype, "credit_amount": round(amt, 2)})

    total_spend = sum(t["amount"] for t in spend)
    company_total = sum(t["amount"] for t in company)
    coffee_total = sum(t["amount"] for t in coffee)
    avoidable_total = sum(t["amount"] for t in avoidable)
    transport_total = sum(t["amount"] for t in transport)
    ev_total = sum(t["amount"] for t in ev_charging)
    tesla_ins_total = sum(t["amount"] for t in tesla_insurance)
    tesla_fsd_total = sum(t["amount"] for t in tesla_fsd)
    tesla_other_total = sum(t["amount"] for t in tesla_other)
    tesla_total = ev_total + tesla_ins_total + tesla_fsd_total + tesla_other_total
    refund_total = sum(abs(t["amount"]) for t in refunds)
    washed_total = sum(float(w["amount"]) for w in washed)
    net_spend = max(total_spend - refund_total, 0)
    all_charges = sorted(
        spend + company, key=lambda t: (t["date"], t.get("cardholder", ""))
    )

    top_merchants = sorted(
        merchant_totals.values(), key=lambda m: float(m["total"]), reverse=True
    )[:15]
    coffee_merchants = sorted(
        coffee_by_merchant.values(), key=lambda m: float(m["total"]), reverse=True
    )
    category_rows = sorted(
        [{"category": k, "total": round(v, 2)} for k, v in by_category.items()],
        key=lambda r: r["total"],
        reverse=True,
    )
    daily = [{"date": d, "total": round(by_day[d], 2)} for d in sorted(by_day)]
    avoidable_cats = sorted(
        [{"category": k, "total": round(v, 2)} for k, v in avoidable_by_category.items()],
        key=lambda r: r["total"],
        reverse=True,
    )
    refund_type_rows = sorted(
        [{"type": k, "total": round(v, 2)} for k, v in refunds_by_type.items()],
        key=lambda r: r["total"],
        reverse=True,
    )
    reattr_by_holder: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {"count": 0, "amount": 0.0}
    )
    for t in spend:
        if t.get("reattributed_from"):
            h = (t.get("cardholder") or "Unknown").strip() or "Unknown"
            reattr_by_holder[h]["count"] = int(reattr_by_holder[h]["count"]) + 1
            reattr_by_holder[h]["amount"] = float(reattr_by_holder[h]["amount"]) + t["amount"]

    cardholder_rows = sorted(
        [
            {
                "cardholder": r["cardholder"],
                "card_ending": r["card_ending"],
                "total": round(float(r["total"]), 2),
                "count": int(r["count"]),
                "coffee": round(float(r["coffee"]), 2),
                "coffee_count": int(r["coffee_count"]),
                "avoidable": round(float(r["avoidable"]), 2),
                "avoidable_count": int(r["avoidable_count"]),
                "share_pct": round(
                    (float(r["total"]) / total_spend * 100) if total_spend else 0, 1
                ),
                "reattributed_count": int(reattr_by_holder[r["cardholder"]]["count"]),
                "reattributed_amount": round(
                    float(reattr_by_holder[r["cardholder"]]["amount"]), 2
                ),
            }
            for r in by_cardholder.values()
        ],
        key=lambda r: r["total"],
        reverse=True,
    )

    days = max(len(by_day), 1)
    coffee_per_day = coffee_total / days if days else 0

    # Merchant totals with spender attribution (for filtered/all views)
    merchant_with_spender: dict[str, dict[str, float | int | str]] = {}
    for t in spend:
        key = f"{t['description'][:60]}|{t.get('cardholder', '')}"
        if key not in merchant_with_spender:
            merchant_with_spender[key] = {
                "merchant": t["description"][:60],
                "cardholder": t.get("cardholder") or "Unknown",
                "total": 0.0,
                "count": 0,
                "category": t["category"],
                "avoidable": t.get("avoidable", False),
                "coffee": t.get("coffee", False),
                "company_expense": t.get("company_expense", False),
            }
        merchant_with_spender[key]["total"] = float(merchant_with_spender[key]["total"]) + t["amount"]
        merchant_with_spender[key]["count"] = int(merchant_with_spender[key]["count"]) + 1
    top_merchants_spender = sorted(
        merchant_with_spender.values(), key=lambda m: float(m["total"]), reverse=True
    )[:20]

    return {
        "statement_id": statement["id"],
        "period_label": statement["period_label"],
        "closing_date": statement["closing_date"],
        "period_start": statement.get("period_start"),
        "period_end": statement.get("period_end"),
        "new_balance": statement.get("new_balance"),
        "minimum_due": statement.get("minimum_due"),
        "payment_due_date": statement.get("payment_due_date"),
        "rewards_points": statement.get("rewards_points"),
        "rewards_as_of": statement.get("rewards_as_of"),
        "cardholder_filter": cardholder if cardholder and cardholder not in {"", "all"} else None,
        "tag_filter": tag if tag and tag not in {"", "all"} else None,
        "cardholders": all_holders,
        "tags": _collect_tags(statement["transactions"]),
        "totals": {
            "spend": round(total_spend, 2),
            "refunds": round(refund_total, 2),
            "net_spend": round(net_spend, 2),
            "washed": round(washed_total, 2),
            "coffee": round(coffee_total, 2),
            "avoidable": round(avoidable_total, 2),
            "company_expense": round(company_total, 2),
            "necessary_estimate": round(max(total_spend - avoidable_total, 0), 2),
            "payments": round(abs(sum(t["amount"] for t in payments)), 2),
            "credits": round(refund_total, 2),
            "transaction_count": len(spend),
            "coffee_count": len(coffee),
            "avoidable_count": len(avoidable),
            "company_expense_count": len(company),
            "transport": round(transport_total, 2),
            "transport_count": len(transport),
            "tesla": round(tesla_total, 2),
            "tesla_count": len(tesla_all),
            "ev_charging": round(ev_total, 2),
            "ev_charging_count": len(ev_charging),
            "tesla_insurance": round(tesla_ins_total, 2),
            "tesla_insurance_count": len(tesla_insurance),
            "tesla_self_driving": round(tesla_fsd_total, 2),
            "tesla_self_driving_count": len(tesla_fsd),
            "tesla_other": round(tesla_other_total, 2),
            "tesla_other_count": len(tesla_other),
            "refund_count": len(refunds),
            "washed_count": len(washed),
            "transfer_count": len(transfers),
            "transfer_in": round(transfer_in, 2),
            "transfer_out": round(transfer_out, 2),
            "amex_send_count": len(transfers),
            "amex_send_in": round(transfer_in, 2),
            "amex_send_out": round(transfer_out, 2),
            "coffee_share_pct": round((coffee_total / total_spend * 100) if total_spend else 0, 1),
            "avoidable_share_pct": round((avoidable_total / total_spend * 100) if total_spend else 0, 1),
            "refund_share_pct": round((refund_total / total_spend * 100) if total_spend else 0, 1),
            "coffee_annualized": round(coffee_per_day * 365, 2),
            "rewards_points": statement.get("rewards_points"),
            "rewards_as_of": statement.get("rewards_as_of"),
        },
        "washed_transactions": sorted(washed, key=lambda w: w["amount"], reverse=True),
        "by_category": category_rows,
        "by_cardholder": cardholder_rows,
        "avoidable_by_category": avoidable_cats,
        "refunds_by_type": refund_type_rows,
        "daily": daily,
        "top_merchants": [
            {
                **m,
                "total": round(float(m["total"]), 2),
                "cardholder": m.get("cardholder", ""),
            }
            for m in top_merchants_spender
        ],
        "coffee_merchants": [
            {**m, "total": round(float(m["total"]), 2)} for m in coffee_merchants
        ],
        "coffee_transactions": sorted(coffee, key=lambda t: (t["date"], t.get("cardholder", ""))),
        "transport_transactions": sorted(
            transport, key=lambda t: t["amount"], reverse=True
        ),
        "tesla_transactions": sorted(tesla_all, key=lambda t: t["amount"], reverse=True),
        "ev_charging_transactions": sorted(
            ev_charging, key=lambda t: t["amount"], reverse=True
        ),
        "tesla_insurance_transactions": sorted(
            tesla_insurance, key=lambda t: t["amount"], reverse=True
        ),
        "tesla_self_driving_transactions": sorted(
            tesla_fsd, key=lambda t: t["amount"], reverse=True
        ),
        "tesla_other_transactions": sorted(
            tesla_other, key=lambda t: t["amount"], reverse=True
        ),
        "avoidable_transactions": sorted(
            avoidable, key=lambda t: t["amount"], reverse=True
        ),
        "refund_transactions": sorted(
            refund_rows, key=lambda t: t["credit_amount"], reverse=True
        ),
        "company_expense_transactions": sorted(
            company, key=lambda t: t["amount"], reverse=True
        ),
        "transfer_transactions": sorted(
            transfers, key=lambda t: (t["date"], t["amount"]), reverse=True
        ),
        "amex_send_transactions": sorted(
            transfers, key=lambda t: (t["date"], t["amount"]), reverse=True
        ),
        "all_spend": all_charges,
        **dining_breakdown(spend),
    }


def _coffee_merchant_key(description: str) -> str:
    upper = description.upper()
    if "STARBUCKS" in upper:
        return "Starbucks"
    if "FAIRGROUNDS" in upper:
        return "Fairgrounds Coffee & Tea"
    if "DISCOURSE" in upper:
        return "Discourse Coffee"
    if "MOKA" in upper:
        return "Moka and Co"
    if "DUNKIN" in upper:
        return "Dunkin"
    return description.split("  ")[0][:40].title()


def _is_starbucks_spend(description: str) -> bool:
    """Starbucks store visits + gift cards (excludes ambiguous phone FOOD&BEV reloads)."""
    upper = (description or "").upper()
    if "STARBUCKS" not in upper:
        return False
    if "GIFT" in upper and "CARD" in upper:
        return True
    if "STORE" in upper:
        return True
    if "APLPAY" in upper:
        return True
    # Phone channel without gift card / store — leave out of Starbucks head-to-head
    if "800-782-7282" in upper:
        return False
    return True


def _member_category_totals(statement: dict) -> dict[str, dict[str, float]]:
    """cardholder -> category -> amount (charges only, after washing exact refunds)."""
    spend, _, _ = _wash_exact_refunds(
        _spend_txs(statement["transactions"]),
        _refund_txs(statement["transactions"]),
    )
    out: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for t in spend:
        holder = (t.get("cardholder") or "Unknown").strip() or "Unknown"
        out[holder][t["category"]] += t["amount"]
        out[holder]["__total__"] += t["amount"]
        if t.get("coffee"):
            out[holder]["__coffee__"] += t["amount"]
        if t.get("avoidable"):
            out[holder]["__avoidable__"] += t["amount"]
        if _is_starbucks_spend(t.get("description") or ""):
            out[holder]["__starbucks_stores__"] += t["amount"]
    return out


def _leader_for_metric(
    member_cats: dict[str, dict[str, float]], metric_key: str, label: str
) -> dict[str, Any] | None:
    ranked = sorted(
        (
            (name, float(cats.get(metric_key, 0.0)))
            for name, cats in member_cats.items()
        ),
        key=lambda x: x[1],
        reverse=True,
    )
    ranked = [(n, v) for n, v in ranked if v > 0]
    if not ranked:
        return None
    winner, win_amt = ranked[0]
    runner = ranked[1] if len(ranked) > 1 else None
    return {
        "metric": label,
        "metric_key": metric_key,
        "winner": winner,
        "amount": round(win_amt, 2),
        "runner_up": runner[0] if runner else None,
        "runner_up_amount": round(runner[1], 2) if runner else 0.0,
        "margin": round(win_amt - (runner[1] if runner else 0.0), 2),
        "ranking": [{"cardholder": n, "amount": round(v, 2)} for n, v in ranked],
    }


def member_leaders(statement: dict) -> list[dict[str, Any]]:
    """Who spent more on coffee, dining, shopping, etc."""
    member_cats = _member_category_totals(statement)
    if len(member_cats) < 1:
        return []

    metrics = [
        ("__starbucks_stores__", "Starbucks (stores + gift cards)"),
        ("__coffee__", "Coffee & cafes"),
        ("__avoidable__", "Avoidable spend"),
        ("__total__", "Total charges"),
        ("Dining Out", "Dining out"),
        ("Shopping / Impulse", "Shopping / impulse"),
        ("Subscriptions", "Subscriptions"),
        ("Groceries", "Groceries"),
        ("Parking & Transit", "Parking & transit"),
        ("Entertainment", "Entertainment"),
        ("Sweets & Bakery", "Sweets & bakery"),
        ("Travel", "Travel"),
        ("Fitness", "Fitness"),
    ]
    leaders = []
    for key, label in metrics:
        row = _leader_for_metric(member_cats, key, label)
        if row:
            leaders.append(row)
    return leaders


def member_leaders_combined(statements: list[dict]) -> list[dict[str, Any]]:
    """Compute member leaders across multiple statements (e.g. all issuers for same period)."""
    all_txs = [t for s in statements for t in (s.get("transactions") or [])]
    if not all_txs:
        return []
    return member_leaders({"transactions": all_txs, "id": "", "period_label": ""})


def member_mom_progress(current: dict, previous: dict | None) -> list[dict[str, Any]]:
    """Per-card-member MoM progress on spend / coffee / avoidable."""
    cur_map = {r["cardholder"]: r for r in summarize_statement(current)["by_cardholder"]}
    prev_map = (
        {r["cardholder"]: r for r in summarize_statement(previous)["by_cardholder"]}
        if previous
        else {}
    )
    names = sorted(set(cur_map) | set(prev_map))
    rows = []
    for name in names:
        c = cur_map.get(name, {})
        p = prev_map.get(name, {})
        metrics = {}
        for key in ("total", "coffee", "avoidable", "coffee_count", "count"):
            cv = float(c.get(key, 0) or 0)
            pv = float(p.get(key, 0) or 0)
            metrics[key] = {
                "current": round(cv, 2) if key != "count" and key != "coffee_count" else int(cv),
                "previous": round(pv, 2) if key != "count" and key != "coffee_count" else int(pv),
                "delta": round(cv - pv, 2),
                "pct": round(((cv - pv) / pv * 100) if pv else (100.0 if cv else 0.0), 1),
            }
        # alias total -> spend for UI clarity
        metrics["spend"] = metrics["total"]
        rows.append(
            {
                "cardholder": name,
                "card_ending": c.get("card_ending") or p.get("card_ending") or "",
                "metrics": metrics,
            }
        )
    rows.sort(key=lambda r: float(r["metrics"]["spend"]["current"]), reverse=True)
    return rows


def compare_statements(
    current: dict, previous: dict | None, cardholder: str | None = None, tag: str | None = None
) -> dict[str, Any]:
    cur = summarize_statement(current, cardholder=cardholder, tag=tag)
    leaders = member_leaders(current)
    mom = member_mom_progress(current, previous)

    if not previous:
        return {
            "current": cur,
            "previous": None,
            "deltas": None,
            "member_leaders": leaders,
            "member_mom": mom,
        }

    prev = summarize_statement(previous, cardholder=cardholder, tag=tag)
    keys = [
        "spend",
        "net_spend",
        "coffee",
        "avoidable",
        "company_expense",
        "refunds",
        "coffee_count",
        "avoidable_count",
        "company_expense_count",
        "refund_count",
    ]
    deltas = {}
    for k in keys:
        c = cur["totals"].get(k)
        p = prev["totals"].get(k)
        if c is None and p is None:
            continue
        c_n = float(c or 0)
        p_n = float(p or 0)
        deltas[k] = {
            "current": round(c_n, 2) if isinstance(c, float) else c_n if c is not None else 0,
            "previous": round(p_n, 2) if isinstance(p, float) else p_n if p is not None else 0,
            "delta": round(c_n - p_n, 2),
            "pct": round(((c_n - p_n) / p_n * 100) if p_n else (100.0 if c_n else 0.0), 1),
        }
    return {
        "current": cur,
        "previous": prev,
        "deltas": deltas,
        "member_leaders": leaders,
        "member_mom": mom,
    }


def ytd_summary(
    statements: list[dict],
    year: int | None = None,
    cardholder: str | None = None,
    tag: str | None = None,
) -> dict[str, Any]:
    """Aggregate coffee / avoidable / category / member spend across a calendar year."""
    if not statements:
        return {"year": year, "statement_count": 0, "totals": {}, "by_category": [], "by_cardholder": [], "by_month": []}

    years = sorted(
        {
            int(str(s.get("closing_date", ""))[:4])
            for s in statements
            if str(s.get("closing_date", "")).startswith(("19", "20"))
        },
        reverse=True,
    )
    target_year = year or (years[0] if years else datetime.now().year)

    year_stmts = [
        s
        for s in statements
        if str(s.get("closing_date", "")).startswith(f"{target_year}-")
    ]
    year_stmts = sorted(year_stmts, key=lambda s: s["closing_date"])

    cat_totals: dict[str, float] = defaultdict(float)
    member_map: dict[str, dict[str, float | int | str]] = {}
    monthly: list[dict[str, Any]] = []

    sum_spend = sum_net = sum_coffee = sum_avoid = sum_company = sum_refunds = 0.0
    sum_coffee_n = sum_avoid_n = sum_company_n = sum_tx = 0
    sum_transport = sum_tesla = 0.0
    sum_transport_n = sum_tesla_n = 0
    sum_ev = sum_tesla_ins = sum_tesla_fsd = sum_tesla_other = 0.0
    sum_ev_n = sum_tesla_ins_n = sum_tesla_fsd_n = sum_tesla_other_n = 0
    sum_transfer_n = 0
    sum_transfer_in = sum_transfer_out = 0.0
    transport_txs: list[dict] = []
    tesla_txs: list[dict] = []
    ev_txs: list[dict] = []
    tesla_ins_txs: list[dict] = []
    tesla_fsd_txs: list[dict] = []
    tesla_other_txs: list[dict] = []
    tesla_mom: list[dict[str, Any]] = []
    transfer_txs: list[dict] = []
    coffee_txs: list[dict] = []
    avoidable_txs: list[dict] = []
    refund_txs: list[dict] = []
    washed_txs: list[dict] = []
    all_spend_txs: list[dict] = []
    merchant_map: dict[str, dict[str, float | int | str]] = {}

    for s in year_stmts:
        summ = summarize_statement(s, cardholder=cardholder, tag=tag)
        t = summ["totals"]
        sum_spend += t["spend"]
        sum_net += t["net_spend"]
        sum_coffee += t["coffee"]
        sum_avoid += t["avoidable"]
        sum_company += t.get("company_expense", 0) or 0
        sum_refunds += t["refunds"]
        sum_coffee_n += t["coffee_count"]
        sum_avoid_n += t["avoidable_count"]
        sum_company_n += t.get("company_expense_count", 0) or 0
        sum_tx += t["transaction_count"]
        sum_transport += t.get("transport", 0) or 0
        sum_transport_n += t.get("transport_count", 0) or 0
        sum_tesla += t.get("tesla", 0) or 0
        sum_tesla_n += t.get("tesla_count", 0) or 0
        sum_ev += t.get("ev_charging", 0) or 0
        sum_ev_n += t.get("ev_charging_count", 0) or 0
        sum_tesla_ins += t.get("tesla_insurance", 0) or 0
        sum_tesla_ins_n += t.get("tesla_insurance_count", 0) or 0
        sum_tesla_fsd += t.get("tesla_self_driving", 0) or 0
        sum_tesla_fsd_n += t.get("tesla_self_driving_count", 0) or 0
        sum_tesla_other += t.get("tesla_other", 0) or 0
        sum_tesla_other_n += t.get("tesla_other_count", 0) or 0
        sum_transfer_n += t.get("transfer_count", t.get("amex_send_count", 0)) or 0
        sum_transfer_in += t.get("transfer_in", t.get("amex_send_in", 0)) or 0
        sum_transfer_out += t.get("transfer_out", t.get("amex_send_out", 0)) or 0
        transport_txs.extend(summ.get("transport_transactions") or [])
        tesla_txs.extend(summ.get("tesla_transactions") or [])
        ev_txs.extend(summ.get("ev_charging_transactions") or [])
        tesla_ins_txs.extend(summ.get("tesla_insurance_transactions") or [])
        tesla_fsd_txs.extend(summ.get("tesla_self_driving_transactions") or [])
        tesla_other_txs.extend(summ.get("tesla_other_transactions") or [])
        transfer_txs.extend(summ.get("transfer_transactions") or summ.get("amex_send_transactions") or [])
        coffee_txs.extend(summ.get("coffee_transactions") or [])
        avoidable_txs.extend(summ.get("avoidable_transactions") or [])
        refund_txs.extend(summ.get("refund_transactions") or [])
        washed_txs.extend(summ.get("washed_transactions") or [])
        all_spend_txs.extend(summ.get("all_spend") or [])

        tesla_mom.append(
            {
                "period_label": s["period_label"],
                "closing_date": s["closing_date"],
                "period_start": s.get("period_start"),
                "period_end": s.get("period_end"),
                "statement_id": s["id"],
                "ev_charging": t.get("ev_charging", 0) or 0,
                "ev_charging_count": t.get("ev_charging_count", 0) or 0,
                "tesla_insurance": t.get("tesla_insurance", 0) or 0,
                "tesla_insurance_count": t.get("tesla_insurance_count", 0) or 0,
                "tesla_self_driving": t.get("tesla_self_driving", 0) or 0,
                "tesla_self_driving_count": t.get("tesla_self_driving_count", 0) or 0,
                "tesla_other": t.get("tesla_other", 0) or 0,
                "tesla_other_count": t.get("tesla_other_count", 0) or 0,
                "tesla": t.get("tesla", 0) or 0,
                "tesla_count": t.get("tesla_count", 0) or 0,
            }
        )

        for row in summ.get("by_category") or []:
            cat_totals[row["category"]] += float(row["total"])

        for row in summ.get("by_cardholder") or []:
            name = row["cardholder"]
            if name not in member_map:
                member_map[name] = {
                    "cardholder": name,
                    "card_ending": row.get("card_ending") or "",
                    "total": 0.0,
                    "count": 0,
                    "coffee": 0.0,
                    "coffee_count": 0,
                    "avoidable": 0.0,
                    "avoidable_count": 0,
                    "company_expense": 0.0,
                }
            m = member_map[name]
            if row.get("card_ending") and not m["card_ending"]:
                m["card_ending"] = row["card_ending"]
            m["total"] = float(m["total"]) + float(row["total"])
            m["count"] = int(m["count"]) + int(row["count"])
            m["coffee"] = float(m["coffee"]) + float(row["coffee"])
            m["coffee_count"] = int(m["coffee_count"]) + int(row["coffee_count"])
            m["avoidable"] = float(m["avoidable"]) + float(row["avoidable"])
            m["avoidable_count"] = int(m["avoidable_count"]) + int(row["avoidable_count"])

        # Company expense isn't in by_cardholder — pull from all_spend if needed
        for tx in summ.get("all_spend") or []:
            if tx.get("company_expense"):
                name = (tx.get("cardholder") or "Unknown").strip() or "Unknown"
                if name not in member_map:
                    member_map[name] = {
                        "cardholder": name,
                        "card_ending": tx.get("card_ending") or "",
                        "total": 0.0,
                        "count": 0,
                        "coffee": 0.0,
                        "coffee_count": 0,
                        "avoidable": 0.0,
                        "avoidable_count": 0,
                        "company_expense": 0.0,
                    }
                member_map[name]["company_expense"] = float(
                    member_map[name]["company_expense"]
                ) + float(tx["amount"])

        monthly.append(
            {
                "period_label": s["period_label"],
                "closing_date": s["closing_date"],
                "period_start": s.get("period_start"),
                "period_end": s.get("period_end"),
                "statement_id": s["id"],
                "issuer": s.get("issuer") or "amex",
                "spend": t["spend"],
                "net_spend": t["net_spend"],
                "coffee": t["coffee"],
                "coffee_count": t["coffee_count"],
                "avoidable": t["avoidable"],
                "avoidable_count": t["avoidable_count"],
                "company_expense": t.get("company_expense", 0) or 0,
                "refunds": t["refunds"],
                "rewards_points": s.get("rewards_points"),
                "rewards_as_of": s.get("rewards_as_of"),
            }
        )

    for tx in all_spend_txs:
        merchant = (tx.get("description") or "")[:60]
        holder = (tx.get("cardholder") or "").strip()
        key = f"{holder}|{merchant}"
        if key not in merchant_map:
            merchant_map[key] = {
                "merchant": merchant,
                "cardholder": holder,
                "category": tx.get("category") or "",
                "total": 0.0,
                "count": 0,
                "avoidable": bool(tx.get("avoidable")),
                "coffee": bool(tx.get("coffee")),
            }
        merchant_map[key]["total"] = float(merchant_map[key]["total"]) + float(tx["amount"])
        merchant_map[key]["count"] = int(merchant_map[key]["count"]) + 1

    # Latest statement's MR balance (not a sum — points are a balance)
    latest = year_stmts[-1] if year_stmts else None
    latest_points = latest.get("rewards_points") if latest else None
    latest_as_of = latest.get("rewards_as_of") if latest else None
    # First non-null earlier balance for delta across year
    first_with_pts = next(
        (s for s in year_stmts if s.get("rewards_points") is not None), None
    )
    points_delta = None
    if (
        latest_points is not None
        and first_with_pts is not None
        and first_with_pts.get("id") != (latest or {}).get("id")
    ):
        points_delta = int(latest_points) - int(first_with_pts["rewards_points"])
    elif latest_points is not None and first_with_pts is not None:
        points_delta = 0

    by_category = sorted(
        [{"category": k, "total": round(v, 2)} for k, v in cat_totals.items()],
        key=lambda r: r["total"],
        reverse=True,
    )
    by_cardholder = sorted(
        [
            {
                "cardholder": r["cardholder"],
                "card_ending": r["card_ending"],
                "total": round(float(r["total"]), 2),
                "count": int(r["count"]),
                "coffee": round(float(r["coffee"]), 2),
                "coffee_count": int(r["coffee_count"]),
                "avoidable": round(float(r["avoidable"]), 2),
                "avoidable_count": int(r["avoidable_count"]),
                "company_expense": round(float(r["company_expense"]), 2),
                "share_pct": round(
                    (float(r["total"]) / sum_spend * 100) if sum_spend else 0, 1
                ),
            }
            for r in member_map.values()
        ],
        key=lambda r: r["total"],
        reverse=True,
    )

    return {
        "year": target_year,
        "statement_count": len(year_stmts),
        "from_date": year_stmts[0]["closing_date"] if year_stmts else None,
        "to_date": year_stmts[-1]["closing_date"] if year_stmts else None,
        "cardholder_filter": cardholder,
        "tag_filter": tag if tag and tag not in {"", "all"} else None,
        "tags": _collect_tags(
            [t for s in year_stmts for t in (s.get("transactions") or [])]
        ),
        "totals": {
            "spend": round(sum_spend, 2),
            "net_spend": round(sum_net, 2),
            "coffee": round(sum_coffee, 2),
            "coffee_count": sum_coffee_n,
            "avoidable": round(sum_avoid, 2),
            "avoidable_count": sum_avoid_n,
            "company_expense": round(sum_company, 2),
            "company_expense_count": sum_company_n,
            "refunds": round(sum_refunds, 2),
            "necessary_estimate": round(max(sum_spend - sum_avoid, 0), 2),
            "transaction_count": sum_tx,
            "coffee_share_pct": round((sum_coffee / sum_spend * 100) if sum_spend else 0, 1),
            "avoidable_share_pct": round(
                (sum_avoid / sum_spend * 100) if sum_spend else 0, 1
            ),
            "transport": round(sum_transport, 2),
            "transport_count": sum_transport_n,
            "tesla": round(sum_tesla, 2),
            "tesla_count": sum_tesla_n,
            "ev_charging": round(sum_ev, 2),
            "ev_charging_count": sum_ev_n,
            "tesla_insurance": round(sum_tesla_ins, 2),
            "tesla_insurance_count": sum_tesla_ins_n,
            "tesla_self_driving": round(sum_tesla_fsd, 2),
            "tesla_self_driving_count": sum_tesla_fsd_n,
            "tesla_other": round(sum_tesla_other, 2),
            "tesla_other_count": sum_tesla_other_n,
            "transfer_count": sum_transfer_n,
            "transfer_in": round(sum_transfer_in, 2),
            "transfer_out": round(sum_transfer_out, 2),
            "amex_send_count": sum_transfer_n,
            "amex_send_in": round(sum_transfer_in, 2),
            "amex_send_out": round(sum_transfer_out, 2),
            "rewards_points": latest_points,
            "rewards_as_of": latest_as_of,
            "rewards_points_delta": points_delta,
        },
        "by_category": by_category,
        "by_cardholder": by_cardholder,
        "by_month": monthly,
        "tesla_mom": tesla_mom,
        "transport_transactions": sorted(
            transport_txs, key=lambda t: t["amount"], reverse=True
        ),
        "tesla_transactions": sorted(tesla_txs, key=lambda t: t["amount"], reverse=True),
        "ev_charging_transactions": sorted(
            ev_txs, key=lambda t: t["amount"], reverse=True
        ),
        "tesla_insurance_transactions": sorted(
            tesla_ins_txs, key=lambda t: t["amount"], reverse=True
        ),
        "tesla_self_driving_transactions": sorted(
            tesla_fsd_txs, key=lambda t: t["amount"], reverse=True
        ),
        "tesla_other_transactions": sorted(
            tesla_other_txs, key=lambda t: t["amount"], reverse=True
        ),
        "transfer_transactions": sorted(
            transfer_txs, key=lambda t: (t["date"], t["amount"]), reverse=True
        ),
        "amex_send_transactions": sorted(
            transfer_txs, key=lambda t: (t["date"], t["amount"]), reverse=True
        ),
        "coffee_transactions": sorted(
            coffee_txs, key=lambda t: (t["date"], t.get("cardholder", ""))
        ),
        "avoidable_transactions": sorted(
            avoidable_txs, key=lambda t: t["amount"], reverse=True
        ),
        "refund_transactions": sorted(
            refund_txs, key=lambda t: float(t.get("credit_amount") or abs(t["amount"])), reverse=True
        ),
        "washed_transactions": sorted(
            washed_txs, key=lambda w: float(w["amount"]), reverse=True
        ),
        "all_spend": sorted(
            all_spend_txs, key=lambda t: (t["date"], t.get("cardholder", ""))
        ),
        "top_merchants": sorted(
            [
                {
                    **m,
                    "total": round(float(m["total"]), 2),
                }
                for m in merchant_map.values()
            ],
            key=lambda m: float(m["total"]),
            reverse=True,
        )[:40],
        **dining_breakdown(all_spend_txs),
    }

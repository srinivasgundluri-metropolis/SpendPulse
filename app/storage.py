"""Local JSON storage for uploaded statements."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from .categorize import build_tags, categorize
from .reattribute import reattribute_statement

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "statements.json"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    if not DB_PATH.exists():
        DB_PATH.write_text("[]", encoding="utf-8")


def _normalize_statement(statement: dict) -> dict:
    """Fill issuer + re-apply categorizer so rule renames take effect."""
    out = dict(statement)
    out.setdefault("issuer", "amex")
    if not out.get("issuer"):
        out["issuer"] = "amex"
    txs = []
    for t in statement.get("transactions") or []:
        row = dict(t)
        cats = categorize(row.get("description") or "", float(row.get("amount") or 0))
        row["category"] = cats["category"]
        row["avoidable"] = cats["avoidable"]
        row["coffee"] = cats["coffee"]
        row["transfer"] = cats["transfer"]
        row["payment"] = cats["payment"] or row.get("kind") == "payment"
        row["credit"] = cats["credit"] or row.get("kind") == "credit"
        row["company_expense"] = bool(cats.get("company_expense"))
        row["tags"] = build_tags(
            cats["category"],
            description=str(row.get("description") or ""),
            coffee=bool(row["coffee"]),
            avoidable=bool(row["avoidable"]),
            company_expense=bool(row["company_expense"]),
            transfer=bool(row["transfer"]),
            payment=bool(row["payment"]),
            credit=bool(row["credit"]),
            kind=str(row.get("kind") or ""),
        )
        txs.append(row)
    out["transactions"] = txs
    return out


def _refresh_categories(statement: dict) -> dict:
    return _normalize_statement(statement)


def load_all() -> list[dict]:
    ensure_dirs()
    try:
        statements = json.loads(DB_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return [reattribute_statement(_normalize_statement(s)) for s in statements]


def save_all(statements: list[dict]) -> None:
    ensure_dirs()
    statements = sorted(statements, key=lambda s: s["closing_date"], reverse=True)
    DB_PATH.write_text(json.dumps(statements, indent=2), encoding="utf-8")


def _issuer_of(statement: dict) -> str:
    return (statement.get("issuer") or "amex").strip().lower() or "amex"


def filter_by_issuer(statements: list[dict], issuer: str | None) -> list[dict]:
    """Return statements for one issuer, or all when issuer is None/all."""
    if not issuer or issuer.strip().lower() in {"", "all", "all cards", "clubbed"}:
        return statements
    key = issuer.strip().lower()
    return [s for s in statements if _issuer_of(s) == key]


def issuers_in_data(statements: list[dict]) -> list[str]:
    seen: list[str] = []
    for s in statements:
        key = _issuer_of(s)
        if key not in seen:
            seen.append(key)
    return seen


def upsert_statement(statement: dict, source_path: Path | None = None) -> dict:
    ensure_dirs()
    statements = load_all()
    statement = dict(statement)
    statement.setdefault("issuer", "amex")
    issuer = _issuer_of(statement)

    # Replace same issuer + closing date (re-upload same month)
    statements = [
        s
        for s in statements
        if not (
            _issuer_of(s) == issuer and s["closing_date"] == statement["closing_date"]
        )
    ]

    if source_path and source_path.exists():
        dest = UPLOADS_DIR / f"{issuer}_{statement['closing_date']}_{statement['filename']}"
        if Path(source_path).resolve() != dest.resolve():
            shutil.copy2(source_path, dest)
        statement["stored_file"] = dest.name
    else:
        statement.setdefault("stored_file", statement["filename"])

    statement = reattribute_statement(statement)
    statements.append(statement)
    save_all(statements)
    return statement


def get_statement(statement_id: str) -> dict | None:
    for s in load_all():
        if s["id"] == statement_id:
            return s
    return None


def delete_statement(statement_id: str) -> bool:
    statements = load_all()
    keep = []
    deleted = None
    for s in statements:
        if s["id"] == statement_id:
            deleted = s
        else:
            keep.append(s)
    if not deleted:
        return False
    save_all(keep)
    stored = deleted.get("stored_file")
    if stored:
        path = UPLOADS_DIR / stored
        if path.exists():
            path.unlink()
    return True


def latest_two(issuer: str | None = None) -> tuple[dict | None, dict | None]:
    statements = load_all()
    if issuer:
        key = issuer.strip().lower()
        statements = [s for s in statements if _issuer_of(s) == key]
    if not statements:
        return None, None
    if len(statements) == 1:
        return statements[0], None
    return statements[0], statements[1]

"""Local spendPulse server (issuer-agnostic shell; Amex parser first)."""

from __future__ import annotations

from typing import Optional
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .activity_import import parse_activity_file
from .analytics import compare_statements, member_leaders_combined, summarize_statement, ytd_summary
from .parsers import (
    DEFAULT_ISSUER,
    ISSUERS,
    can_import_activity,
    can_parse,
    issuer_label,
    list_issuers,
    parse_statement,
)
from .storage import (
    delete_statement,
    ensure_dirs,
    filter_by_issuer,
    get_statement,
    issuers_in_data,
    latest_two,
    load_all,
    upsert_statement,
)

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "static"

app = FastAPI(title="spendPulse", version="1.2.0")
ensure_dirs()


def _normalize_issuer_filter(issuer: Optional[str]) -> str | None:
    if not issuer or issuer.strip().lower() in {"", "all", "all cards", "clubbed"}:
        return None
    return issuer.strip().lower()


def _statement_brief(s: dict) -> dict:
    return {
        "id": s["id"],
        "issuer": s.get("issuer") or DEFAULT_ISSUER,
        "issuer_label": issuer_label(s.get("issuer")),
        "period_label": s["period_label"],
        "closing_date": s["closing_date"],
        "period_start": s.get("period_start"),
        "period_end": s.get("period_end"),
    }


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True, "issuers": list_issuers()}


@app.get("/api/issuers")
def issuers():
    return {
        "issuers": list_issuers(),
        "default": DEFAULT_ISSUER,
        "parseable": [i["id"] for i in list_issuers() if i.get("can_parse")],
    }


@app.get("/api/statements")
def list_statements(issuer: Optional[str] = None):
    statements = filter_by_issuer(load_all(), _normalize_issuer_filter(issuer))
    return [
        {
            **_statement_brief(s),
            "filename": s["filename"],
            "new_balance": s.get("new_balance"),
            "transaction_count": len(s.get("transactions", [])),
            "uploaded_at": s.get("uploaded_at"),
        }
        for s in statements
    ]


@app.get("/api/statements/{statement_id}")
def statement_detail(statement_id: str):
    statement = get_statement(statement_id)
    if not statement:
        raise HTTPException(404, "Statement not found")
    return summarize_statement(statement)


@app.get("/api/dashboard")
def dashboard(
    statement_id: Optional[str] = None,
    cardholder: Optional[str] = None,
    tag: Optional[str] = None,
    issuer: Optional[str] = None,
):
    all_statements = load_all()
    issuer_f = _normalize_issuer_filter(issuer)
    statements = filter_by_issuer(all_statements, issuer_f)

    if not all_statements:
        return {
            "has_data": False,
            "statements": [],
            "current": None,
            "previous": None,
            "deltas": None,
            "issuer_filter": None,
            "issuers": list_issuers(),
        }

    if not statements:
        return {
            "has_data": True,
            "statements": [],
            "current": None,
            "previous": None,
            "deltas": None,
            "issuer_filter": issuer_f,
            "issuer_filter_label": issuer_label(issuer_f) if issuer_f else "All cards",
            "issuers": _issuers_payload(all_statements),
            "ytd": ytd_summary([], cardholder=None, tag=None),
            "empty_issuer": True,
            "message": f"No statements for {issuer_label(issuer_f)} yet — upload one or switch to All cards.",
        }

    if statement_id and statement_id != "ytd":
        current = get_statement(statement_id)
        if not current:
            raise HTTPException(404, "Statement not found")
        # Respect issuer filter: statement must belong to filtered set
        if issuer_f and (current.get("issuer") or DEFAULT_ISSUER).lower() != issuer_f:
            raise HTTPException(404, "Statement not found for this issuer filter")
        cur_issuer = (current.get("issuer") or DEFAULT_ISSUER).lower()
        older = [
            s
            for s in all_statements
            if s["closing_date"] < current["closing_date"]
            and (s.get("issuer") or DEFAULT_ISSUER).lower() == cur_issuer
        ]
        previous = older[0] if older else None
    else:
        # Latest within filtered set (All cards → newest across issuers)
        current, previous = latest_two(issuer_f)
        # MoM always compares within the same issuer (even in All cards view)
        if current and not issuer_f:
            cur_issuer = (current.get("issuer") or DEFAULT_ISSUER).lower()
            older = [
                s
                for s in all_statements
                if s["closing_date"] < current["closing_date"]
                and (s.get("issuer") or DEFAULT_ISSUER).lower() == cur_issuer
            ]
            previous = older[0] if older else None

    member = cardholder if cardholder and cardholder.lower() != "all" else None
    tag_f = tag if tag and tag.lower() != "all" else None
    comparison = compare_statements(current, previous, cardholder=member, tag=tag_f)

    # In All Cards view the "current" statement is one issuer only (newest overall).
    # Recompute leaders using the most recent statement from each issuer so the
    # comparison spans all household cards, not just one.
    if not issuer_f and current:
        seen_issuers: set[str] = set()
        multi_issuer: list[dict] = []
        for s in all_statements:  # sorted newest-first
            iss = (s.get("issuer") or "amex").lower()
            if iss not in seen_issuers:
                seen_issuers.add(iss)
                multi_issuer.append(s)
        if len(multi_issuer) > 1:
            comparison["member_leaders"] = member_leaders_combined(multi_issuer)

    ytd = ytd_summary(statements, cardholder=member, tag=tag_f)
    return {
        "has_data": True,
        "statements": [_statement_brief(s) for s in statements],
        "cardholder_filter": member,
        "tag_filter": tag_f,
        "issuer_filter": issuer_f,
        "issuer_filter_label": issuer_label(issuer_f) if issuer_f else "All cards",
        "issuers": _issuers_payload(all_statements),
        "ytd": ytd,
        **comparison,
    }


def _issuers_payload(statements: list[dict]) -> list[dict]:
    """Known issuers + any present in data, with statement counts."""
    counts: dict[str, int] = {}
    for s in statements:
        key = (s.get("issuer") or DEFAULT_ISSUER).lower()
        counts[key] = counts.get(key, 0) + 1
    rows = []
    seen = set()
    for row in list_issuers(include_unparseable=True):
        key = row["id"]
        seen.add(key)
        rows.append({**row, "statement_count": counts.get(key, 0)})
    for key in issuers_in_data(statements):
        if key in seen:
            continue
        rows.append(
            {
                "id": key,
                "label": issuer_label(key),
                "can_parse": can_parse(key),
                "statement_count": counts.get(key, 0),
            }
        )
    return rows


@app.post("/api/upload")
async def upload_statement(
    file: UploadFile = File(...),
    issuer: Optional[str] = Form(None),
):
    if not file.filename:
        raise HTTPException(400, "Missing filename")
    lower = file.filename.lower()
    is_pdf = lower.endswith(".pdf")
    is_activity = lower.endswith((".csv", ".xlsx", ".xls", ".xlsm"))
    if not is_pdf and not is_activity:
        raise HTTPException(
            400, "Upload a statement PDF or an activity CSV / Excel export."
        )

    issuer_key = (issuer or DEFAULT_ISSUER).strip().lower() or DEFAULT_ISSUER
    if issuer_key not in ISSUERS:
        raise HTTPException(400, f"Unknown issuer {issuer_key!r}.")

    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Empty file")

    with tempfile.NamedTemporaryFile(suffix=Path(file.filename).suffix, delete=False) as tmp:
        tmp.write(raw)
        tmp_path = Path(tmp.name)

    try:
        if is_activity:
            if not can_import_activity(issuer_key):
                raise HTTPException(400, f"Unknown issuer {issuer_key!r}.")
            statements = parse_activity_file(tmp_path, issuer=issuer_key)
            if not statements:
                raise HTTPException(400, "No transactions found in this file.")
            saved_list = []
            for stmt in statements:
                d = stmt.to_dict()
                d["source"] = "activity_export"
                saved_list.append(upsert_statement(d, source_path=tmp_path))
            saved = saved_list[0]
            months = len(saved_list)
            charge_n = sum(
                summarize_statement(s)["totals"]["transaction_count"] for s in saved_list
            )
            summary = summarize_statement(saved)
            return {
                "ok": True,
                "message": (
                    f"Imported {issuer_label(issuer_key)} activity → {months} month"
                    f"{'s' if months != 1 else ''} · {charge_n} charges"
                ),
                "statement": {
                    "id": saved["id"],
                    "issuer": saved.get("issuer") or issuer_key,
                    "period_label": saved["period_label"],
                    "closing_date": saved["closing_date"],
                },
                "months_imported": months,
                "summary": summary["totals"],
            }

        if not can_parse(issuer_key):
            raise HTTPException(
                400,
                f"{issuer_label(issuer_key)} PDF parsing is not available yet — "
                "upload a CSV/Excel activity export instead, or pick American Express for PDFs.",
            )
        statement = parse_statement(tmp_path, filename=file.filename, issuer=issuer_key)
        saved = upsert_statement(statement.to_dict(), source_path=tmp_path)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Could not parse statement: {exc}") from exc
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)

    summary = summarize_statement(saved)
    return {
        "ok": True,
        "message": (
            f"Imported {issuer_label(saved.get('issuer'))} {summary['period_label']} — "
            f"{summary['totals']['transaction_count']} charges"
        ),
        "statement": {
            "id": saved["id"],
            "issuer": saved.get("issuer") or DEFAULT_ISSUER,
            "period_label": saved["period_label"],
            "closing_date": saved["closing_date"],
        },
        "summary": summary["totals"],
    }


@app.delete("/api/statements/{statement_id}")
def remove_statement(statement_id: str):
    if not delete_statement(statement_id):
        raise HTTPException(404, "Statement not found")
    return {"ok": True}


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

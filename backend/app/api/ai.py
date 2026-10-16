"""AI Reviewer and Review Risk Score. Every AI output is grounded in a deterministic context, validated claim by
claim, stored in `ai_runs`, and read-only: no endpoint here changes the workpaper."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..deps import Ctx, require
from ..models import AIRun
from ..packet.refs import resolve
from ..security.masking import mask_payload, mask_text
from ..security.roles import Perm
from ..services import ai as AI
from ..services import audit, risk
from ..services.assurance import challenge
from .collaboration import _items, _names

router = APIRouter(prefix="/api")


def _fmt(v) -> str:
    return f"{v:,.0f}" if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v)


def _scored(c: Ctx) -> list[dict]:
    return risk.score_items(c.db, c.idx, c.engagement.id, _items(c))


@router.get("/review/risk")
def review_risk(c: Ctx = Depends(require(Perm.VIEW_INTERNAL_NOTES))):
    scored = _scored(c)
    return mask_payload({"items": scored, "areas": risk.by_area(scored),
                         "components": [{"key": k, "label": lbl, "max": mx} for k, (lbl, mx) in risk.COMPONENTS.items()],
                         "method": "Sum of named components, capped at 100: high ≥ 50, medium ≥ 25. Each component cites its evidence."})


@router.get("/ai/status")
def ai_status(c: Ctx = Depends(require(Perm.VIEW_INTERNAL_NOTES))):
    p = AI.provider()
    return {"provider": p.name, "model": p.model, "is_ai": p.name != "grounded_template",
            "note": "A Claude model is used when TAXPROOF_AI_API_KEY is set; otherwise TaxProof writes deterministic sentences "
                    "from the same evidence (not AI). Either way every claim is validated against the evidence it cites."}


def _record(c: Ctx, task: str, subject: str | None, result: dict) -> AIRun:
    run = AIRun(engagement_id=c.engagement.id, task=task, subject=subject, provider=result["provider"], model=result["model"],
                context_sha256=result["context_sha256"], context={"facts": result["context"]}, raw_output=result["raw"],
                claims=result["claims"], supported=result["supported"], rejected=result["rejected"], error=result["error"],
                created_by_id=c.user.id)
    c.db.add(run)
    c.db.flush()
    audit.record(c.db, c.engagement.id, "ai.run", actor_id=c.user.id, actor_role=c.user.role, target_ref=subject,
                 payload={"run_id": run.id, "task": task, "provider": run.provider, "model": run.model,
                          "supported": run.supported, "rejected": run.rejected, "context_sha256": run.context_sha256})
    c.db.commit()
    return run


def _run_dict(r: AIRun, names: dict[str, str]) -> dict:
    return mask_payload({"id": r.id, "task": r.task, "subject": r.subject, "provider": r.provider, "model": r.model,
                         "is_ai": r.provider != "grounded_template", "claims": r.claims, "supported": r.supported,
                         "rejected": r.rejected, "error": r.error, "context": r.context.get("facts", []),
                         "context_sha256": r.context_sha256, "created_by": names.get(r.created_by_id), "created_at": r.created_at})


@router.post("/ai/brief")
def reviewer_brief(c: Ctx = Depends(require(Perm.VIEW_INTERNAL_NOTES))):
    """Rank what the reviewer should look at first, from the risk-scored open items."""
    scored = _scored(c)[:10]
    if not scored:
        raise HTTPException(409, "Nothing is open: there is nothing to brief.")
    facts = []
    for n, s in enumerate(scored, 1):
        reasons = "; ".join(f"{x['label'].lower()}: {x['reason'].rstrip('.')}" for x in s["components"][:3])
        refs = list(dict.fromkeys(s["refs"] + [r for x in s["components"] for r in x["refs"]]))[:12]
        facts.append(AI.fact(f"F{n}", f"Risk {s['score']} ({s['level']}): {s['title'].rstrip('.')}. {reasons}.", refs + [s["key"]], [s["score"]]))
    run = _record(c, "reviewer_brief", None, AI.run("reviewer_brief", facts))
    return _run_dict(run, _names(c))


class ExplainIn(BaseModel):
    finding_id: str = Field(min_length=3, max_length=200)
    version: str | None = Field(default=None, max_length=10)


def _page_text(c: Ctx, ref: str) -> str | None:
    r = resolve(c.idx, ref)
    if r.kind == "page" and r.exists:
        doc = c.idx.documents_by_id[r.document_id]
        page = next((p for p in doc["pages"] if p["page"] == r.page), None)
        return page and page["printed_content"][:600]
    if r.kind == "extracted_value" and r.exists:
        ev = c.idx.values_by_id[ref]
        return f"{ev['label']} read as '{ev['text_as_read']}' (confidence {ev['confidence']:.0%}) on {ev['document_id']} page {ev['page']}"
    return None


@router.post("/ai/explain")
def explain_finding(body: ExplainIn, c: Ctx = Depends(require(Perm.VIEW_INTERNAL_NOTES))):
    v = body.version or c.idx.current_version
    if v not in c.idx.versions_by_id:
        raise HTTPException(404, f"Unknown return version '{v}'.")
    f = next((x for x in challenge(c.idx, v) if x.id == body.finding_id), None)
    if f is None:
        raise HTTPException(404, f"No finding '{body.finding_id}' in {v}.")
    ev = list(f.evidence)
    outcome = {"fail": "failed", "pass": "passed", "attention": "needs judgment", "explained": "is explained"}.get(f.status, f.status)
    facts = [AI.fact("F1", f"In return version {v}, TaxProof's check {outcome} ({f.status}): {f.title}. {f.summary}",
                     ev + [f"line:{v}:{k}" for k in f.lines[:3]])]
    if f.engine and f.independent:
        facts.append(AI.fact("F2", f"The supplied engine has {_fmt(f.engine['value'])}; TaxProof's independent value is {_fmt(f.independent['value'])} "
                                   f"({f.independent.get('method') or 'independent check'}).",
                             [r for r in [f.engine.get("ref") and f"line:{v}:{f.engine['ref']}"] if r] + ev[:3],
                             [f.engine["value"], f.independent["value"], f.difference or 0]))
    for i, b in enumerate(f.breakdown[:6]):
        facts.append(AI.fact(f"B{i + 1}", f"{b.get('label')}: {_fmt(b.get('value'))}", [b["ref"]] if b.get("ref") else ev[:2],
                             [b.get("value")] if isinstance(b.get("value"), (int, float)) else []))
    for i, ref in enumerate([r for r in ev if r.startswith(("doc:", "ev-"))][:4]):
        txt = _page_text(c, ref)
        if txt:
            facts.append(AI.fact(f"E{i + 1}", f"Evidence {ref}: {txt}", [ref]))
    if f.effect:
        facts.append(AI.fact("T1", f"Estimated effect: federal {_fmt(f.effect.get('federal'))}, California {_fmt(f.effect.get('california'))} "
                                   f"({f.effect.get('basis', '')[:200]})", ev[:2], [f.effect.get("federal") or 0, f.effect.get("california") or 0]))
    run = _record(c, "explain_finding", f"finding:{f.id}@{v}", AI.run("explain_finding", facts))
    return _run_dict(run, _names(c))


class DraftIn(BaseModel):
    item_key: str = Field(min_length=3, max_length=200)


@router.post("/ai/draft-question")
def draft_question(body: DraftIn, c: Ctx = Depends(require(Perm.ASK_CLIENT))):
    item = next((i for i in _items(c) if i.key == body.item_key), None)
    if item is None:
        raise HTTPException(404, f"No inbox item '{body.item_key}'.")
    evidence = item.detail.get("evidence") or []
    facts = [AI.fact("F1", f"{item.title}. {item.summary}", list(item.refs) + list(evidence)[:4])]
    run = _record(c, "draft_question", item.key, AI.run("draft_question", facts))
    out = _run_dict(run, _names(c))
    supported = [x for x in out["claims"] if x["status"] == "supported"]
    return out | {"question": mask_text(supported[0]["text"]) if supported else None}


@router.get("/ai/runs")
def ai_runs(c: Ctx = Depends(require(Perm.VIEW_INTERNAL_NOTES))):
    names = _names(c)
    rows = c.db.scalars(select(AIRun).where(AIRun.engagement_id == c.engagement.id).order_by(AIRun.id.desc()).limit(50)).all()
    return [_run_dict(r, names) for r in rows]

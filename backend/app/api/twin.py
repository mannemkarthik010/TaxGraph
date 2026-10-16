"""Return Assurance Twin API: the dashboard, "Why should I trust this return?" and what changed since you looked."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select

from ..deps import Ctx, require
from ..models import Adjustment, AuditEvent, FiledSnapshot, Judgment, Verification, ViewMark
from ..security.masking import mask_payload
from ..security.roles import Perm
from ..services import ai as AI
from ..services import audit, risk, standards
from ..services import filing as F
from ..services import inbox as IB
from ..services import twin as T
from ..services.adjustments import workpaper_summary
from ..services.assurance import challenge
from ..services.returns import return_summary
from .collaboration import _board, _items, _names
from .filing import _approval, _scripted_approval_spent

router = APIRouter(prefix="/api")

CLOSING = "Traditional workpapers document what the preparer did. TaxProof continuously proves why the filed return should be trusted."
CHANGE_LABELS = {
    "adjustment": "Adjustments", "signoff": "Sign-offs", "review_note": "Review notes", "note": "Notes", "judgment": "Judgments",
    "client_question": "Client questions", "verification": "Verifications", "evidence_link": "Evidence links", "inbox": "Inbox decisions",
    "filing": "Filing", "amendment": "Amendments", "notice_response": "Notice responses", "firm": "Firm standards", "time": "Time",
}
NOISE = {"permission.denied", "ai.run", "twin.trust_report", "sensitive.reveal", "sensitive.reveal_denied"}


def _assemble(c: Ctx) -> dict[str, Any]:
    v = c.idx.current_version
    items = _items(c)
    board = _board(c, items)
    readiness = IB.readiness(items, board)
    findings = challenge(c.idx, v)
    verified = {x.target_ref for x in c.db.scalars(select(Verification).where(
        Verification.engagement_id == c.engagement.id, Verification.status == "active")).all()}
    judgments = list(c.db.scalars(select(Judgment).where(Judgment.engagement_id == c.engagement.id)).all())
    applied = list(c.db.scalars(select(Adjustment).where(Adjustment.engagement_id == c.engagement.id, Adjustment.version == v,
                                                          Adjustment.status == "applied")).all())
    docs = T.documents(c.idx, v)
    trace = T.traceability(c.idx, v)
    cov = T.coverage(c.idx, v, verified)
    chk = T.checks(findings, items)
    jud = T.judgments(items, judgments)
    sig = T.signoffs(board)
    state = F.state(c.db, c.engagement.id)
    evs = F.events(c.db, c.engagement.id)
    current_fp = F.fingerprint(c.db, c.idx, c.engagement.id)["sha256"]
    client_fp = _approval(evs, "client_approved_and_signed_8879")
    client_ok = bool(client_fp and client_fp["sha256"] == current_fp) or state in F.POST_FILING
    awaiting = state == "partner_approved" and _scripted_approval_spent(c, evs)
    blockers = [i for i in items if i.status == "open" and i.blocks_filing]
    snaps = list(c.db.scalars(select(FiledSnapshot).where(FiledSnapshot.engagement_id == c.engagement.id).order_by(FiledSnapshot.id)).all())
    broken = [s for s in snaps if not F.verify(s)["valid"]]
    scored = risk.score_items(c.db, c.idx, c.engagement.id, items)
    critical = [s for s in scored if s["level"] == "high"]
    non_pass = chk["total"] - chk["passed"]
    parts = {
        "documents": (docs["accounted"] / docs["total"], f"{docs['accounted']} of {docs['total']} documents used, superseded or not used for a recorded reason.", "/evidence"),
        "traceability": (trace["traceable"] / max(1, trace["material"]),
                         f"{trace['traceable']} of {trace['material']} lines of {T.MATERIAL:,.0f} or more trace to cited evidence.", "/prove"),
        "coverage": (cov["verified"] / max(1, cov["values"]), f"{cov['verified']} of {cov['values']} values feeding the return verified by a person.", "/evidence"),
        "checks": ((chk["passed"] + chk["dispositioned"]) / max(1, chk["total"]),
                   f"{chk['passed']} of {chk['total']} checks passed; {chk['dispositioned']} of {non_pass} others dispositioned.", "/challenge"),
        "judgments": (jud["decided"] / max(1, jud["items"]) if jud["items"] else 1.0,
                      f"{jud['decided']} of {jud['items']} judgment items decided; {jud['approved']} of {jud['recorded']} recorded judgments approved.",
                      "/review?tab=judgments"),
        "review": (sig["reviewed"] / sig["areas"], f"{sig['reviewed']} of {sig['areas']} areas reviewed"
                   + (f"; {len(sig['reopened'])} sign-off(s) reopened" if sig["reopened"] else "") + ".", "/review?tab=signoffs"),
        "partner": (sig["partner"] / sig["areas"], f"{sig['partner']} of {sig['areas']} areas partner-approved.", "/review?tab=signoffs"),
        "client": (1.0 if client_ok else 0.0, "The client approved exactly the return now on file." if client_ok
                   else "The client has not approved the current return.", "/filing"),
        "blockers": (0.0 if broken else max(0.0, 1 - len(blockers) / 10),
                     f"{len(broken)} filed snapshot(s) fail their integrity check." if broken else f"{len(blockers)} open filing blocker(s).",
                     "/filing" if broken else "/review?tab=inbox"),
    }
    prevent = T.what_prevents_filing(readiness, state, F.STATE_LABEL[state], client_ok, awaiting)
    if broken:  # a filed record that no longer matches its hash cannot be relied on, whatever else is true
        prevent.insert(0, {"kind": "integrity", "key": "snapshot_integrity", "label": "A filed snapshot does not match its hash",
                           "count": len(broken), "items": [f"Snapshot #{s.id} ({s.kind}, filed {s.filed_at[:10]}): stored content was altered "
                                                           f"after filing" for s in broken], "link": "/filing"})
    summary = return_summary(c.idx, v)
    snap = F.latest_snapshot(c.db, c.engagement.id)
    return {
        "version": v, "engine": summary["summary"], "headlines": summary["headlines"],
        "workpaper": workpaper_summary(c.idx, v, applied),
        "filed": {"snapshot_id": snap.id, "kind": snap.kind, "filed_at": snap.filed_at, "summary": snap.content.get("filed_summary"),
                  "integrity": not broken, "broken": [s.id for s in broken]} if snap else None,
        "lifecycle": {"state": state, "label": F.STATE_LABEL[state], "jurisdictions": F.jurisdictions(c.db, c.engagement.id),
                      "client_authorized": client_ok, "awaiting_client": awaiting},
        "assurance": T.score(parts),
        "documents": docs, "traceability": trace, "coverage": cov, "checks": chk, "judgments": jud, "signoffs": sig,
        "readiness": readiness, "what_prevents_filing": prevent, "can_file_now": not prevent,
        "critical": critical[:8], "critical_count": len(critical), "risk_areas": risk.by_area(scored)[:6],
        "inbox": {"open": sum(1 for i in items if i.status == "open"), "blocking": len(blockers)},
        "standards_version": standards.version(),
    }


def _since(c: Ctx) -> dict[str, Any]:
    mark = c.db.scalar(select(ViewMark).where(ViewMark.engagement_id == c.engagement.id, ViewMark.user_id == c.user.id,
                                              ViewMark.scope == "dashboard"))
    if mark is None:
        return {"seen_at": None, "first_visit": True, "groups": [], "events": []}
    rows = c.db.scalars(select(AuditEvent).where(AuditEvent.engagement_id == c.engagement.id, AuditEvent.seq > mark.seen_seq)
                        .order_by(AuditEvent.seq.desc())).all()
    rows = [e for e in rows if e.action not in NOISE and e.actor_id != c.user.id]
    names = _names(c)
    groups: dict[str, int] = {}
    for e in rows:
        g = CHANGE_LABELS.get(e.action.split(".")[0], e.action.split(".")[0])
        groups[g] = groups.get(g, 0) + 1
    return {"seen_at": mark.seen_at, "first_visit": False, "groups": [{"label": k, "count": n} for k, n in sorted(groups.items(), key=lambda x: -x[1])],
            "events": [{"seq": e.seq, "at": e.at, "action": e.action, "by": names.get(e.actor_id or "", "system"), "target_ref": e.target_ref}
                       for e in rows[:25]]}


@router.get("/twin")
def dashboard(c: Ctx = Depends(require(Perm.VIEW_INTERNAL_NOTES))):
    return mask_payload(_assemble(c) | {"since": _since(c)})


@router.post("/twin/seen")
def mark_seen(c: Ctx = Depends(require(Perm.VIEW_INTERNAL_NOTES))):
    last = c.db.scalar(select(AuditEvent.seq).where(AuditEvent.engagement_id == c.engagement.id).order_by(AuditEvent.seq.desc()).limit(1)) or 0
    mark = c.db.scalar(select(ViewMark).where(ViewMark.engagement_id == c.engagement.id, ViewMark.user_id == c.user.id,
                                              ViewMark.scope == "dashboard"))
    if mark is None:
        mark = ViewMark(engagement_id=c.engagement.id, user_id=c.user.id, scope="dashboard")
        c.db.add(mark)
    mark.seen_at, mark.seen_seq = datetime.now(timezone.utc), last
    c.db.commit()
    return {"seen_at": mark.seen_at, "seen_seq": last}


def _status(ok: bool, partial: bool = False) -> str:
    return "good" if ok else "warn" if partial else "bad"


@router.get("/twin/trust")
def trust_report(c: Ctx = Depends(require(Perm.VIEW_INTERNAL_NOTES))):
    """Why should I trust this return? Each answer is computed, cites where to see it, and says what is missing."""
    t = _assemble(c)
    d, tr, cov, ch, j, s, lc = t["documents"], t["traceability"], t["coverage"], t["checks"], t["judgments"], t["signoffs"], t["lifecycle"]
    open_issues = t["inbox"]["open"]
    sections = [
        {"key": "documents", "question": "Are all documents accounted for?", "answer": f"{d['accounted']} of {d['total']}",
         "status": _status(d["accounted"] == d["total"]), "detail": f"{d['by_status'].get('used', 0)} used, {d['by_status'].get('superseded', 0)} superseded, "
         f"{len(d['not_used'])} not used for a recorded reason; {len(d['issues'])} document-level reading issues flagged.",
         "items": [f"{x['id']} — {x['reason']}" for x in d["not_used"]] + [f"{x['id']} — {x['label']}: {x['detail']}" for x in d["issues"][:6]],
         "link": "/evidence"},
        {"key": "traceability", "question": "Can the material numbers be traced to evidence?", "answer": f"{tr['traceable']} of {tr['material']}",
         "status": _status(tr["traceable"] == tr["material"], tr["traceable"] / max(1, tr["material"]) >= 0.9),
         "detail": f"Lines of {tr['threshold']:,.0f} or more whose inputs reach a cited document, value or record (not only engine rules).",
         "items": [f"{x['key']} {x['label']} ({x['rule']})" for x in tr["untraceable"][:8]], "link": "/prove"},
        {"key": "checks", "question": "Did the independent checks pass?", "answer": f"{ch['passed']} passed · {ch['failed']} failed · {ch['attention']} need judgment",
         "status": _status(not ch["open"], ch["dispositioned"] > 0),
         "detail": f"{ch['dispositioned']} of {ch['total'] - ch['passed']} non-passing checks dispositioned (adjustment, judgment, client answer or accepted with explanation).",
         "items": [f"{x['title']} ({x['status']})" for x in ch["open"][:8]], "link": "/challenge"},
        {"key": "issues", "question": "What is still unresolved?", "answer": f"{open_issues} open item(s), {t['inbox']['blocking']} blocking",
         "status": _status(open_issues == 0, t["inbox"]["blocking"] == 0), "detail": "Every open item in the Uncertainty Inbox.",
         "items": [f"{x['title']} (risk {x['score']})" for x in t["critical"][:6]], "link": "/review?tab=inbox"},
        {"key": "judgments", "question": "Are the judgment calls documented?", "answer": f"{j['decided']} of {j['items']} decided · {j['approved']} of {j['recorded']} approved",
         "status": _status(not j["open"] and not j["awaiting_review"], j["decided"] > 0),
         "detail": "Each recorded judgment carries its decision, alternatives, rationale, authority, evidence and tax effect.",
         "items": [f"Open: {x['title']}" for x in j["open"][:5]] + [f"Awaiting review: #{x['id']} {x['topic']}" for x in j["awaiting_review"][:5]],
         "link": "/review?tab=judgments"},
        {"key": "review", "question": "Is the review complete?", "answer": f"{s['reviewed']} of {s['areas']} areas reviewed",
         "status": _status(s["reviewed"] == s["areas"], s["reviewed"] > 0),
         "detail": "Active reviewed sign-offs; a change underneath reopens them.", "items": [f"{r['area']} {r['level']} reopened: {r['reason']}" for r in s["reopened"][:5]],
         "link": "/review?tab=signoffs"},
        {"key": "partner", "question": "Has the partner signed?", "answer": f"{s['partner']} of {s['areas']} areas",
         "status": _status(s["partner"] == s["areas"], s["partner"] > 0), "detail": "Active partner sign-offs per area.", "items": [], "link": "/review?tab=signoffs"},
        {"key": "client", "question": "Has the client authorized it?", "answer": "Yes" if lc["client_authorized"] else "No",
         "status": _status(lc["client_authorized"]), "detail": "Forms 8879 / FTB 8879 signed for exactly the content now on file." if lc["client_authorized"]
         else "No client approval matches the current return." + (" The client approves again in TaxProof." if lc["awaiting_client"] else ""),
         "items": [], "link": "/filing"},
        {"key": "filing", "question": "What is the filing status?", "answer": lc["label"],
         "status": "bad" if t["filed"] and not t["filed"]["integrity"] else _status(lc["state"] in F.POST_FILING, lc["state"] in ("submitted", "accepted")),
         "detail": (f"Filed {t['filed']['filed_at'][:10]}; " + ("every filed snapshot matches its hash." if t["filed"]["integrity"]
                    else f"the filed record does not match its hash (snapshot {', '.join(f'#{i}' for i in t['filed']['broken'])}): it was altered after filing.")
                    if t["filed"] else "Not filed yet."), "items": [f"{k}: {v.get('status')} ({v.get('submission_id')})" for k, v in lc["jurisdictions"].items()],
         "link": "/filing"},
    ]
    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "version": t["version"], "lifecycle": lc, "assurance": t["assurance"],
              "sections": sections, "what_prevents_filing": t["what_prevents_filing"],
              "verdict": (f"Filed, but the filed record fails its integrity check: {len(t['filed']['broken'])} snapshot(s) do not match their hash."
                          if t["filed"] and not t["filed"]["integrity"]
                          else "Filed and defended: nothing prevents filing." if lc["state"] in F.POST_FILING
                          else "Nothing in the workpaper prevents filing." if not t["what_prevents_filing"]
                          else f"{len(t['what_prevents_filing'])} thing(s) prevent filing — listed exactly below."),
              "closing": CLOSING}
    report["report_sha256"] = F.canonical_hash({k: v for k, v in report.items() if k != "generated_at"})
    audit.record(c.db, c.engagement.id, "twin.trust_report", actor_id=c.user.id, actor_role=c.user.role,
                 payload={"report_sha256": report["report_sha256"], "score": t["assurance"]["score"], "blockers": len(t["what_prevents_filing"])})
    c.db.commit()
    return mask_payload(report)


@router.post("/twin/trust/summary")
def trust_summary(c: Ctx = Depends(require(Perm.VIEW_INTERNAL_NOTES))):
    """A short grounded narrative of the trust report: every sentence cites the section it rests on."""
    from .ai import _record, _run_dict
    t = trust_report(c)
    facts = [AI.fact(f"S{i + 1}", f"{s['question']} {s['answer']}. {s['detail']}", [f"twin:{s['key']}"]) for i, s in enumerate(t["sections"])]
    facts.append(AI.fact("P1", "What prevents filing: " + ("; ".join(f"{b['label']} ({b['count']})" for b in t["what_prevents_filing"]) or "nothing") + ".",
                         ["twin:what_prevents_filing"]))
    run = _record(c, "trust_summary", "twin", AI.run("trust_summary", facts))
    return _run_dict(run, _names(c))

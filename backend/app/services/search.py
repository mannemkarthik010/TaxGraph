"""Firm-wide search over the packet and the workpaper.

Two layers, both deterministic and explainable (no external embedding service — the semantic signal is learned
locally from the packet; pgvector would slot in at the `rank` step):
  1. **Intent handlers** answer questions that have an exact, computed answer — "why did tax increase from v2
     to v3?" (Time Machine drivers), "unresolved basis issues" (open inbox items about basis), "low-confidence
     extractions" (values read below 80% that reach the return).
  2. **Concept search**: BM25 over every searchable object (return lines, documents and pages, extracted
     values, client answers / messages / call notes, timeline, TaxProof findings, engine diagnostics,
     judgments), with a small tax-concept lexicon so "California move" also finds residency, Texas, part-year,
     540NR …, and term associations learned from this file itself (pointwise mutual information of
     co-occurrence), so related words the lexicon does not know still count. Every hit says which terms matched.
     Blended with a **semantic** signal: cosine similarity in a latent space learned from the packet by LSA
     (`semantic.py`), so an object that shares no words with the query can still rank; such hits say which of
     their words sit closest to the query ("related").
All text is masked before it is indexed or returned.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from ..packet.index import PacketIndex
from ..security.masking import mask_text
from .areas import area_for_line
from .assurance import challenge

try:
    from . import semantic
except ImportError:  # numpy absent: BM25 + lexicon + associations only
    semantic = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

STOP = set("the a an of to in on for and or is are was were be by with from at as it this that these those what which who why "
           "how show me everything all any do did does me my our your its into than then there their about supporting".split())
CONCEPTS: dict[str, list[str]] = {
    "move": ["moved", "residency", "resident", "nonresident", "part-year", "texas", "austin", "sacramento", "relocat"],
    "california": ["ftb", "california", "sacramento", "residency", "part-year", "nonresident"],
    "basis": ["basis", "cost", "7203", "8949", "adjusted", "stock"],
    "crypto": ["btc", "bitcoin", "coinhaven", "digital", "wallet", "cryptonorth"],
    "mileage": ["miles", "mileage", "vehicle", "car", "log", "44a"],
    "charity": ["charitable", "donation", "gift", "8283", "contribution", "noncash"],
    "rental": ["rental", "rent", "fremont", "schedule", "repairs", "hvac"],
    "income": ["receipts", "revenue", "1099", "wages", "income"],
    "payment": ["payment", "estimated", "transcript", "extension", "4868", "ftb"],
}


def _stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > 4 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def tokens(text: str) -> list[str]:
    words = (w.rstrip(".-") for w in re.findall(r"[a-z0-9][a-z0-9.\-]*", (text or "").lower()))
    return [_stem(w) for w in words if w and w not in STOP]


@dataclass
class Doc:
    ref: str
    kind: str
    title: str
    text: str
    link: str | None = None


_INDEX: dict[str, tuple[list[Doc], list[Counter], dict[str, int], float]] = {}
_POSTINGS: dict[str, dict[str, set[int]]] = {}
_ASSOC: dict[tuple[str, str], list[tuple[str, float]]] = {}
SEM_WEIGHT = 0.3   # share of the final score from semantic similarity; the rest is BM25, normalised per query
SEM_FLOOR = 0.45   # below this cosine the latent space is guessing; such similarity adds nothing
KIND_WEIGHT = {"Client answer (accepted)": 1.6, "Adjustment": 1.1, "Review note": 1.0, "Note": 0.9, "Client answer": 1.5, "Client message": 1.4, "Call note": 1.4, "Household": 1.6, "Timeline": 1.2, "Document": 1.2,
               "Page": 1.1, "TaxProof finding": 1.2, "Judgment": 1.3, "Return line": 0.7}


def _docs(idx: PacketIndex) -> list[Doc]:
    v = idx.current_version
    out: list[Doc] = []
    for ln in idx.versions_by_id[v]["lines"]:
        out.append(Doc(f"line:{v}:{ln['key']}", "Return line", f"{ln['key']} {ln['label']}",
                       f"{ln['label']} {ln['form']} {area_for_line(ln)} {ln.get('note') or ''} {ln['value']}"))
    for d in idx.data["documents"]:
        out.append(Doc(d["id"], "Document", f"{d['id']} {d['title']}", f"{d['title']} {d.get('type') or ''}"))
        for p in d["pages"]:
            out.append(Doc(f"doc:{d['id']}#page{p['page']}", "Page", f"{d['id']} page {p['page']} — {d['title']}",
                           mask_text(p["printed_content"]) or ""))
    for ev in idx.data["extracted_values"]:
        out.append(Doc(ev["id"], "Extracted value", f"{ev['id']} {ev['label']}",
                       mask_text(f"{ev['label']} {ev['field']} {ev['text_as_read']} {ev['document_id']}") or ""))
    c = idx.data["client"]
    for q in c["questionnaire"]:
        out.append(Doc(q["id"], "Client answer", f"{q['id']} {q['question']}", f"{q['question']} {q['answer']}"))
    for m in c["messages"]:
        out.append(Doc(m["id"], "Client message", f"{m['id']} from {m['from']}", m["text"]))
    for cn in c["call_notes"]:
        out.append(Doc(cn["id"], "Call note", f"{cn['id']} {cn['date'][:10]}", " ".join(cn["notes"])))
    for t in idx.data["timeline"]:
        out.append(Doc(t["id"], "Timeline", f"{t['at'][:10]} {t['event'].replace('_', ' ')}",
                       f"{t['event'].replace('_', ' ')} {t.get('detail') or ''} {' '.join(t['refs'])}"))
    for f in challenge(idx, v):
        if f.status != "pass":
            out.append(Doc(f"finding:{f.id}", "TaxProof finding", f.title, f"{f.title} {f.summary} {f.family}",
                           f"/challenge?finding={f.id}"))
    for dg in idx.versions_by_id[v]["diagnostics"]:
        out.append(Doc(f"diag:{dg['code']}", "Engine diagnostic", dg["code"], f"{dg['code'].replace('_', ' ')} {dg['message']}"))
    res = idx.data["household"].get("residency")
    if res:
        out.append(Doc("household:residency", "Household", "Residency", mask_text(str(res)) or ""))
    return out


def workpaper_docs(db: Any, engagement_id: str) -> list[Doc]:
    """Workpaper evidence and decisions, searched live (they change): accepted client answers, judgments,
    adjustments and review notes. Masked like everything else."""
    from sqlalchemy import select

    from ..models import Adjustment, ClientQuestion, Judgment, WorkpaperNote
    out = []
    for q in db.scalars(select(ClientQuestion).where(ClientQuestion.engagement_id == engagement_id, ClientQuestion.status == "accepted")).all():
        out.append(Doc(f"client_answer:{q.id}", "Client answer (accepted)", mask_text(q.question[:120]) or "",
                       mask_text(f"{q.question} {q.answer or ''} {q.acceptance_note or ''}") or ""))
    for j in db.scalars(select(Judgment).where(Judgment.engagement_id == engagement_id, Judgment.status != "superseded")).all():
        out.append(Doc(f"judgment:{j.id}", "Judgment", mask_text(j.topic) or "", mask_text(f"{j.topic} {j.decision} {j.rationale} {j.authority}") or ""))
    for a in db.scalars(select(Adjustment).where(Adjustment.engagement_id == engagement_id, Adjustment.status != "undone")).all():
        out.append(Doc(f"adjustment:{a.id}", "Adjustment", f"Adjustment #{a.id} on {a.target_line}", mask_text(a.reason) or ""))
    for n in db.scalars(select(WorkpaperNote).where(WorkpaperNote.engagement_id == engagement_id)).all():
        out.append(Doc(f"note:{n.id}", "Review note" if n.kind == "review_note" else "Note", f"Note on {n.target_ref}",
                       mask_text(f"{n.body} {n.resolution or ''}") or ""))
    return out


def _index(idx: PacketIndex) -> tuple[list[Doc], list[Counter], dict[str, int], float]:
    key = idx.packet.sha256
    if key not in _INDEX:
        docs = _docs(idx)
        tfs = [Counter(tokens(d.title + " " + d.text)) for d in docs]
        df: dict[str, int] = defaultdict(int)
        for tf in tfs:
            for t in tf:
                df[t] += 1
        avg = sum(sum(tf.values()) for tf in tfs) / max(1, len(tfs))
        _INDEX[key] = (docs, tfs, dict(df), avg)
        postings: dict[str, set[int]] = defaultdict(set)
        for i, tf in enumerate(tfs):
            for t in tf:
                postings[t].add(i)
        _POSTINGS[key] = dict(postings)
    return _INDEX[key]


def associations(idx: PacketIndex, term: str, k: int = 6) -> list[tuple[str, float]]:
    """Terms that co-occur with `term` in this file far more than chance (pointwise mutual information over
    documents, pages, answers and notes): a distributional, corpus-learned notion of relatedness — "sacramento"
    → residency, moved, part-year … Weights are normalised to (0, 1]."""
    key = (idx.packet.sha256, term)
    if key in _ASSOC:
        return _ASSOC[key]
    docs, tfs, df, _avg = _index(idx)
    postings = _POSTINGS[idx.packet.sha256]
    n = len(docs)
    hits = postings.get(term, set())
    if not hits or len(hits) > n * 0.2:              # unknown, or too common to say anything
        _ASSOC[key] = []
        return []
    co: Counter = Counter()
    for i in hits:
        co.update(tfs[i].keys())
    scored = []
    for w, c in co.items():
        if w == term or c < 2 or len(w) < 4 or not w[0].isalpha() or df.get(w, 0) < 2 or df[w] > n * 0.2:
            continue
        pmi = math.log((c * n) / (len(hits) * df[w]))
        if pmi > 1.0:
            scored.append((w, pmi * math.log(1 + c)))
    scored.sort(key=lambda x: -x[1])
    top = scored[:k]
    best = top[0][1] if top else 1.0
    _ASSOC[key] = [(w, round(sc / best, 3)) for w, sc in top]
    return _ASSOC[key]


def expand(query: str) -> tuple[list[str], list[str]]:
    q = tokens(query)
    extra = []
    for t in q:
        for concept, words in CONCEPTS.items():
            if t.startswith(_stem(concept)) or t in {_stem(w) for w in words}:
                extra += [_stem(w) for w in words + [concept]]
    return q, [w for w in dict.fromkeys(extra) if w not in q]


def learned(idx: PacketIndex, query: str) -> list[tuple[str, float]]:
    q, lexicon = expand(query)
    seen = set(q) | set(lexicon)
    out: dict[str, float] = {}
    for t in q:
        for w, wt in associations(idx, t):
            if w not in seen:
                out[w] = max(out.get(w, 0), wt)
    return sorted(out.items(), key=lambda x: -x[1])[:10]


def rank(idx: PacketIndex, query: str, extra_docs: list[Doc] | None = None, limit: int = 25) -> list[dict[str, Any]]:
    docs, tfs, df, avg = _index(idx)
    q, expansion = expand(query)
    assoc = learned(idx, query)
    weighted = [(t, 1.0) for t in q] + [(t, 0.4) for t in expansion] + [(t, 0.25 * w) for t, w in assoc]
    base_kinds = [d.kind for d in docs]
    if extra_docs:
        docs = docs + extra_docs
        tfs = tfs + [Counter(tokens(d.title + " " + d.text)) for d in extra_docs]
    sem = _semantic(idx, base_kinds, tfs, dict(weighted))
    sims = sem[1] if sem else None
    n = len(docs)
    raw = []
    for i, (d, tf) in enumerate(zip(docs, tfs)):
        length = sum(tf.values()) or 1
        s, matched = 0.0, []
        for term, weight in weighted:
            hits = sum(c for w, c in tf.items() if w == term or (len(term) >= 4 and w.startswith(term)))
            if not hits:
                continue
            idf = math.log(1 + (n - df.get(term, 1) + 0.5) / (df.get(term, 1) + 0.5))
            s += weight * idf * hits * 2.2 / (hits + 1.2 * (0.25 + 0.75 * length / avg))
            matched.append(term)
        sim = float(sims[i]) if sims is not None else 0.0
        if s > 0 or sim > SEM_FLOOR:
            raw.append((s, i, matched, sim))
    # Hybrid score: BM25 normalised by this query's best, blended with how far the cosine clears the floor.
    top = max((s for s, *_ in raw), default=0.0) or 1.0
    scores = []
    for s, i, matched, sim in raw:
        blended = (1 - SEM_WEIGHT) * s / top + SEM_WEIGHT * max(0.0, sim - SEM_FLOOR) / (1 - SEM_FLOOR)
        # Evidence answers "what supports X" better than the return lines it feeds; computed lines rank lower.
        scores.append((100 * blended * KIND_WEIGHT.get(docs[i].kind, 1.0), i, matched, sim))
    scores.sort(key=lambda x: -x[0])
    out = []
    for s, i, m, sim in scores[:limit]:
        d = docs[i]
        related = sem[0].space.nearest_terms(sem[2], tfs[i], set(m) | {t for t, _ in weighted}) if sem and sim > SEM_FLOOR else []
        out.append({"ref": d.ref, "kind": d.kind, "title": mask_text(d.title), "snippet": _snippet(d.text, set(m) | set(related)),
                    "score": round(s, 2), "matched": m, "semantic": round(sim, 2), "related": related, "link": d.link})
    return out


def _semantic(idx: PacketIndex, base_kinds: list[str], tfs: list[Counter], weighted: dict[str, float]) -> tuple[Any, Any, Any] | None:
    """(latent index, cosine of the query to every doc, query vector), or None when the semantic layer is unavailable
    or the query has no word it knows — search then runs on BM25 alone."""
    if not semantic_available():
        return None
    try:
        sem = semantic.index(idx.packet.sha256, base_kinds, tfs[: len(base_kinds)])
        qv = sem.space.embed_query(weighted) if weighted else None
        return None if qv is None else (sem, sem.similarities(qv, tfs[len(base_kinds):]), qv)
    except Exception:  # noqa: BLE001 - a ranking signal must never take search down
        log.exception("semantic layer failed; falling back to BM25")
        return None


def warm(idx: PacketIndex) -> None:
    """Build the search index and the latent space at startup (both cached by packet hash)."""
    docs, tfs, _df, _avg = _index(idx)
    _semantic(idx, [d.kind for d in docs], tfs, {})


def semantic_available() -> bool:
    return semantic is not None


def method() -> str:
    base = ("Computed answers for recognised questions, then BM25 text search with a tax-concept lexicon and term "
            "associations learned from this file (co-occurrence / PMI)")
    if not semantic_available():
        return base + ". Semantic layer unavailable (numpy not installed): lexical ranking only."
    return (base + f", blended {int(SEM_WEIGHT * 100)}/{100 - int(SEM_WEIGHT * 100)} with semantic similarity from a "
            f"{semantic.DIMS}-dimension latent space (LSA) learned locally from this packet. No external model or embedding service; "
            "nothing leaves the server.")


def _snippet(text: str, terms: set[str]) -> str:
    text = mask_text(text) or ""
    words = text.split()
    for i, w in enumerate(words):
        if _stem(re.sub(r"[^a-z0-9.\-]", "", w.lower())) in terms:
            return " ".join(words[max(0, i - 12): i + 20])[:240]
    return text[:240]


# ---- intents ------------------------------------------------------------------------------------------------

INTENTS = (
    ("version_change", re.compile(r"\b(why|what)\b.*\b(tax|return|change[ds]?)\b.*\b(v\d)\b.*\b(v\d)\b", re.I)),
    ("open_basis", re.compile(r"\b(unresolved|open|outstanding)\b.*\bbasis\b|\bbasis\b.*\b(issues?|problems?|unresolved)\b", re.I)),
    ("low_confidence", re.compile(r"low[- ]confidence|uncertain (read|extraction)|confidence", re.I)),
)


def intent(query: str) -> tuple[str, re.Match] | None:
    for name, rx in INTENTS:
        m = rx.search(query)
        if m:
            return name, m
    return None

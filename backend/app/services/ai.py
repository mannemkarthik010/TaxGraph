"""AI, used only where it is useful and never trusted on its own.

The model is given a *context*: numbered facts, each with the references that support it and the numbers it
contains, all built deterministically from the packet and the workpaper and masked first. It must answer with
claims, each citing references. Every claim is then validated:

  1. it cites at least one reference;
  2. every reference it cites was given to it in the context (it cannot introduce evidence);
  3. every material number in its text appears in the facts behind the references it cites — and does not
     contradict their sign or direction (+1,222 / "increases" against a stated -1,222);
  4. it does not claim to have taken an action (changed a number, resolved, approved, filed …);
  5. it asserts no status the cited facts do not state ("verified", "ready to file", "all", "approved" …);
  6. it says something the cited facts say (enough of its terms appear in them);
  7. it neither negates what its relevant cited facts say nor drops a negation they state;
  8. it does not swap whose figure a number is (the engine's vs TaxProof's independent value).
Malformed output is rejected claim by claim; a model that returns nothing usable falls back to the template.

Claims that fail are rejected and shown as rejected, with the reason; they are never presented as findings.
AI output is advisory and read-only: nothing in this module writes to the workpaper.

Providers:
  - "anthropic": a Claude model, used only when TAXPROOF_AI_API_KEY is set (model TAXPROOF_AI_MODEL,
    default claude-opus-5-5). Only the masked context is sent.
  - "grounded_template": deterministic sentences built from the same facts, used when no model is configured
    (and in tests). It is labelled as such — it is not AI.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..security.masking import mask_payload, mask_text

ACTION_CLAIMS = re.compile(r"\b(I|we|TaxProof) (have |has )?(changed|adjusted|updated|corrected|resolved|approved|signed|filed|"
                           r"closed|accepted|deleted|removed)\b", re.IGNORECASE)
NUMBER = re.compile(r"(?<![\w.])-?\$?\(?\d{1,3}(?:,\d{3})+(?:\.\d+)?\)?|(?<![\w.:#-])-?\$?\d{3,}(?:\.\d+)?(?![\w-])")


@dataclass
class Fact:
    id: str
    text: str
    refs: list[str]
    numbers: list[float] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "text": self.text, "refs": self.refs, "numbers": self.numbers}


def numbers_in(text: str) -> list[float]:
    out = []
    for m in NUMBER.finditer(text or ""):
        raw = m.group(0).replace("$", "").replace(",", "")
        neg = raw.startswith("-") or (raw.startswith("(") and raw.endswith(")"))
        raw = raw.strip("()-")
        try:
            val = float(raw)
        except ValueError:
            continue
        out.append(-val if neg else val)
    return out


def fact(fid: str, text: str, refs: list[str], extra_numbers: list[float] | None = None) -> Fact:
    text = mask_text(text) or ""
    nums = numbers_in(text) + [float(x) for x in (extra_numbers or []) if isinstance(x, (int, float))]
    return Fact(fid, text, sorted(set(refs)), nums)


def context_hash(task: str, facts: list[Fact]) -> str:
    return hashlib.sha256(json.dumps({"task": task, "facts": [f.as_dict() for f in facts]}, sort_keys=True).encode()).hexdigest()


# ---- validation -----------------------------------------------------------------------------------------

SIGNED = re.compile(r"(?P<sign>[+\-−])?\$?(?P<paren>\()?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{3,}(?:\.\d+)?)\)?(?![\w-])")
UP = re.compile(r"\b(increase[sd]?|rais(?:e|es|ed|ing)|higher|grows?|grew|rises?|rose|goes up|went up|adds?|added|more tax)\b", re.I)
DOWN = re.compile(r"\b(decrease[sd]?|reduc(?:e|es|ed|ing)|lower(?:s|ed)?|falls?|fell|drops?|dropped|cuts?|saves?|goes down|went down|less tax)\b", re.I)
ASSERTIONS = {
    "verification": re.compile(r"\b(verified|confirmed|reconciled|substantiated|validated)\b", re.I),
    "readiness": re.compile(r"\b(ready to (?:be )?file|ready for filing|can be filed|good to file|safe to file)\b", re.I),
    "completeness": re.compile(r"\b(all|every|entire(?:ly)?|complete(?:ly)?|fully|nothing (?:is )?(?:open|missing)|no (?:other )?(?:issues?|problems?|exceptions?|open items?))\b", re.I),
    "approval": re.compile(r"\b(approved|signed off|cleared|accepted)\b", re.I),
}
STOP = set("the this that these those with from into onto over under about after before while where when which what were was been being "
           "have has had does did doing will would could should their there here they them then than also only just some such each "
           "page pages line lines amount amounts value values evidence return".split())
MIN_OVERLAP = 0.34
NEGATION = re.compile(r"\b(not|no|never|none|neither|nor|without|cannot)\b|n't\b", re.I)
ROLES = {"the engine": re.compile(r"\b(engine|supplied|reported)\b", re.I),
         "TaxProof's independent value": re.compile(r"\b(independent|taxproof|recomputed|recalculated)\b", re.I)}


def _signed(text: str) -> list[tuple[float, int]]:
    """Numbers with their sign: -1 / +1 when the text states it (sign, parentheses or a direction word just
    before), 0 when it is a plain magnitude."""
    out = []
    for m in SIGNED.finditer(text or ""):
        try:
            val = float(m.group("num").replace(",", ""))
        except ValueError:
            continue
        sign = 0
        if m.group("sign") in ("-", "−") or m.group("paren"):
            sign = -1
        elif m.group("sign") == "+":
            sign = 1
        else:
            before = text[max(0, m.start() - 40):m.start()]
            ups, downs = list(UP.finditer(before)), list(DOWN.finditer(before))
            last_up = ups[-1].end() if ups else -1
            last_down = downs[-1].end() if downs else -1
            sign = 1 if last_up > last_down else -1 if last_down > last_up else 0
        out.append((val, sign))
    return out


def _roles(text: str) -> list[tuple[float, str | None]]:
    """Each material number with whose figure the sentence says it is (the engine's or TaxProof's independent
    value): the last role word before it in the same clause, or None."""
    out = []
    for m in SIGNED.finditer(text or ""):
        try:
            val = float(m.group("num").replace(",", ""))
        except ValueError:
            continue
        before = text[max(0, m.start() - 60):m.start()]
        before = re.split(r"[;.]\s", before)[-1]
        found = [(rx_m.end(), role) for role, rx in ROLES.items() for rx_m in rx.finditer(before)]
        out.append((val, max(found)[1] if found else None))
    return out


def _content(text: str) -> set[str]:
    return {w[:6] for w in re.findall(r"[a-z][a-z'-]{3,}", (text or "").lower()) if w not in STOP}


def validate(claims: Any, facts: list[Fact], task: str | None = None) -> list[dict[str, Any]]:
    """Validate claims against the facts they cite (see module docstring). Never raises on bad input."""
    allowed = {r for f in facts for r in f.refs} | {f.id for f in facts}
    texts_by_ref: dict[str, list[str]] = {}
    signed_by_ref: dict[str, list[tuple[float, int]]] = {}
    for f in facts:
        for r in f.refs + [f.id]:
            texts_by_ref.setdefault(r, []).append(f.text)
            in_text = _signed(f.text)
            extra = [(abs(n), 0) for n in f.numbers if not any(abs(abs(n) - v) <= 1 for v, _ in in_text)]
            signed_by_ref.setdefault(r, []).extend(in_text + extra)
    out = []
    for c in claims if isinstance(claims, list) else [claims]:
        if not isinstance(c, dict) or not isinstance(c.get("text"), str) or not isinstance(c.get("refs", []), list):
            out.append({"text": mask_text(str(c.get("text")) if isinstance(c, dict) else str(c))[:300] if c is not None else "",
                        "refs": [], "status": "rejected", "problems": ["malformed claim (expected {text, refs})"], "kind": None})
            continue
        text = mask_text(c["text"]).strip()
        refs = [str(r) for r in c.get("refs") or []]
        problems = []
        if not text:
            problems.append("empty claim")
        if not refs:
            problems.append("cites no evidence")
        foreign = [r for r in refs if r not in allowed]
        if foreign:
            problems.append(f"cites evidence it was not given: {', '.join(foreign[:5])}")
        cited_facts = [t for r in refs for t in texts_by_ref.get(r, [])]
        cited_text = " ".join(cited_facts)
        support = [x for r in refs for x in signed_by_ref.get(r, [])]
        for val, sign in _signed(text):
            if val < 100:
                continue
            same = [(v, s) for v, s in support if abs(v - val) <= 1]
            if not same:
                problems.append(f"number not in the cited evidence: {val:,.0f}")
            elif sign and all(s and s != sign for _, s in same):
                what = "sign" if re.search(rf"[+\-−]\$?{re.escape(f'{val:,.0f}')}|\(\$?{re.escape(f'{val:,.0f}')}\)", text) else "direction"
                problems.append(f"{what} contradicts the cited evidence for {val:,.0f}")
        fact_roles = [x for t in cited_facts for x in _roles(t)]
        for val, role in _roles(text):
            if val < 100 or role is None:
                continue
            same = [r for v, r in fact_roles if abs(v - val) <= 1 and r]
            if same and role not in same:
                problems.append(f"attributes {val:,.0f} to {role}; the cited evidence gives it as {same[0]}")
        if ACTION_CLAIMS.search(text):
            problems.append("claims to have taken an action (AI cannot change the workpaper)")
        if task != "draft_question" and text and refs and not foreign:
            for name, rx in ASSERTIONS.items():
                if rx.search(text) and not rx.search(cited_text):
                    problems.append(f"asserts {name} ('{rx.search(text).group(0)}') not stated in the cited evidence")
            words = _content(text)
            relevant = [t for t in cited_facts if words and len(words & _content(t)) / len(words) >= 0.4]
            if relevant:
                claim_neg = bool(NEGATION.search(text))
                if claim_neg and not any(NEGATION.search(t) for t in relevant):
                    problems.append("negates what the cited evidence says")
                elif not claim_neg and all(NEGATION.search(t) for t in relevant):
                    problems.append("drops the negation the cited evidence states")
            if len(words) >= 3:
                hit = len(words & _content(cited_text)) / len(words)
                if hit < MIN_OVERLAP:
                    problems.append(f"says things not stated in the cited evidence ({hit:.0%} of its terms appear there)")
        out.append({"text": text, "refs": refs, "status": "rejected" if problems else "supported", "problems": problems,
                    "kind": c.get("kind")})
    return out


# ---- providers ------------------------------------------------------------------------------------------

INSTRUCTIONS = {
    "reviewer_brief": "Write a reviewer brief for a CPA reviewing this tax return. Rank what to review first, most "
                      "important first: suspicious evidence, missing documents, unexplained differences, unusual "
                      "prior-year variances, conflicts, incomplete verification, risky judgments. 3 to 8 claims.",
    "explain_finding": "Explain this independent finding to a reviewer in plain language: what was found, why it "
                       "matters and what evidence shows it. 2 to 5 claims.",
    "trust_summary": "Summarize, for a partner deciding whether to sign, how far this return is proven and what still "
                     "prevents filing. 3 to 6 claims, most important first.",
    "draft_question": "Draft one short, polite question to the client (the taxpayer, not a tax professional) that "
                      "would settle this item. One claim whose text is the question. Do not include identifiers.",
}
SYSTEM = ("You assist a CPA firm. You may only use the facts provided. Answer with JSON only: "
          '{"claims": [{"text": "...", "refs": ["<reference ids from the facts>"]}]}. Every claim must cite the '
          "references of the facts it relies on; never cite anything else; never invent numbers; never say you "
          "changed, approved, resolved or filed anything — you cannot act.")


class Provider:
    name = "base"
    model: str | None = None

    def complete(self, task: str, facts: list[Fact]) -> tuple[str, list[dict[str, Any]]]:
        raise NotImplementedError


class GroundedTemplate(Provider):
    """Deterministic writer over the same facts: not AI, and labelled so."""

    name = "grounded_template"

    def complete(self, task: str, facts: list[Fact]) -> tuple[str, list[dict[str, Any]]]:
        if task == "draft_question":
            f = facts[0]
            subject = re.sub(r"\s+", " ", f.text.split(". ")[0]).rstrip(".:?")[:160]
            text = (f"We want to make sure your return is right about this: \"{subject}\". Could you confirm the facts for us, "
                    "and send any document that shows them?")
            # keep the question free of numbers the client would have to decode
            claims = [{"text": re.sub(NUMBER, "the amount", text), "refs": f.refs[:3] or [f.id]}]
        else:
            claims = [{"text": f.text, "refs": f.refs or [f.id]} for f in facts[:12]]
        return json.dumps({"claims": claims}), claims


class Anthropic(Provider):
    name = "anthropic"

    def __init__(self, key: str, model: str, base_url: str):
        self.key, self.model, self.base_url = key, model, base_url.rstrip("/")

    def complete(self, task: str, facts: list[Fact]) -> tuple[str, list[dict[str, Any]]]:
        prompt = INSTRUCTIONS[task] + "\n\nFacts:\n" + json.dumps(mask_payload([f.as_dict() for f in facts]), indent=1)
        r = httpx.post(f"{self.base_url}/v1/messages", timeout=60,
                       headers={"x-api-key": self.key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                       json={"model": self.model, "max_tokens": 1500, "system": SYSTEM,
                             "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()
        raw = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
        m = re.search(r"\{.*\}", raw, re.S)
        claims = json.loads(m.group(0)).get("claims", []) if m else []
        return raw, claims if isinstance(claims, list) else []


def provider() -> Provider:
    """Claude when a key is configured (TAXPROOF_AI_API_KEY in the environment or backend/.env), else the template."""
    from ..config import settings
    key = os.environ.get("TAXPROOF_AI_API_KEY") or settings.ai_api_key
    if key:
        return Anthropic(key, os.environ.get("TAXPROOF_AI_MODEL") or settings.ai_model,
                         os.environ.get("TAXPROOF_AI_BASE_URL") or settings.ai_base_url)
    return GroundedTemplate()


def run(task: str, facts: list[Fact], prov: Provider | None = None) -> dict[str, Any]:
    """Run a task and validate the result. A failing model call falls back to the grounded template, saying so."""
    prov = prov or provider()
    error = None
    try:
        raw, claims = prov.complete(task, facts)
        claims = claims if isinstance(claims, list) else []
    except Exception as e:  # network, quota, malformed JSON — never let the review stop
        error = f"{prov.name} failed ({type(e).__name__}); used the grounded template instead."
        prov = GroundedTemplate()
        raw, claims = prov.complete(task, facts)
    checked = validate(claims, facts, task)
    usable = [c for c in checked if not any(p.startswith("malformed") for p in c["problems"])]
    if prov.name != "grounded_template" and not usable:
        error = f"{prov.name} returned no usable claims; used the grounded template instead."
        prov = GroundedTemplate()
        raw, claims = prov.complete(task, facts)
        checked = validate(claims, facts, task)
    return {"provider": prov.name, "model": prov.model, "is_ai": prov.name != "grounded_template", "raw": raw,
            "claims": checked, "supported": sum(1 for c in checked if c["status"] == "supported"),
            "rejected": sum(1 for c in checked if c["status"] == "rejected"), "error": error,
            "context": [f.as_dict() for f in facts], "context_sha256": context_hash(task, facts)}

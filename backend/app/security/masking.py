"""Sensitive-data masking.

Masking is applied server-side before any response leaves the API. Everyone sees masked values by
default; a cleared user can reveal one field at a time through the reveal endpoint, which is logged.
"""

from __future__ import annotations

import re
from typing import Any

MASK = "•"

SSN_RE = re.compile(r"\b(\d{3})-(\d{2})-(\d{4})\b")
IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[0-9A-Z]{4}){3,7}(?: ?[0-9A-Z]{1,3})?\b")
PIN_RE = re.compile(r"(PIN\b[^.;]{0,60}?)\b(\d{5,6})\b")
ACCOUNT_RE = re.compile(r"(\b(?:account|routing)(?: number)?:?\s+)(\d[\d-]{5,}\d)", re.IGNORECASE)

SENSITIVE_VALUE_TYPES = {"ssn", "account_number"}


def mask_ssn(value: str | None) -> str | None:
    if not value:
        return value
    digits = re.sub(r"\D", "", value)
    return f"{MASK * 3}-{MASK * 2}-{digits[-4:]}" if len(digits) >= 4 else MASK * 4


def mask_tail(value: str | None, keep: int = 4) -> str | None:
    if not value:
        return value
    raw = str(value)
    alnum = re.sub(r"[^0-9A-Za-z]", "", raw)
    return f"{MASK * 4}{alnum[-keep:]}" if len(alnum) > keep else MASK * len(alnum)


def mask_pin(value: str | None) -> str | None:
    return MASK * 6 if value else value


def mask_text(text: str | None) -> str | None:
    """Mask SSNs, IBANs, signature/IP PINs and long account numbers inside free text (e.g. printed_content)."""
    if not text:
        return text
    out = SSN_RE.sub(lambda m: f"{MASK * 3}-{MASK * 2}-{m.group(3)}", text)
    out = IBAN_RE.sub(lambda m: mask_tail(m.group(0)), out)
    out = PIN_RE.sub(lambda m: m.group(1) + MASK * len(m.group(2)), out)
    out = ACCOUNT_RE.sub(lambda m: m.group(1) + mask_tail(m.group(2)), out)
    return out


def mask_payload(value: Any) -> Any:
    """`mask_text` applied to every string in a payload, however deeply nested (dicts, lists, tuples).

    Used on every response that carries text people typed (notes, reasons, judgments, client answers,
    history, graph metadata), so a new field can never become a way around masking.
    """
    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, dict):
        return {k: mask_payload(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [mask_payload(v) for v in value]
    return value


def is_sensitive_value(ev: Any) -> bool:
    return ev.get("value_type") in SENSITIVE_VALUE_TYPES or "pin" in str(ev.get("field", "")).lower().split("_")


def mask_extracted_value(ev: Any) -> dict[str, Any]:
    out = dict(ev)
    if is_sensitive_value(ev):
        if ev.get("value_type") == "ssn":
            out["value"], out["text_as_read"] = mask_ssn(ev.get("value")), mask_ssn(ev.get("text_as_read"))
        elif "pin" in str(ev.get("field", "")).lower():
            out["value"], out["text_as_read"] = mask_pin(ev.get("value")), mask_pin(ev.get("text_as_read"))
        else:
            out["value"], out["text_as_read"] = mask_tail(ev.get("value")), mask_tail(ev.get("text_as_read"))
        out["masked"] = True
    return out


# Household fields that are sensitive, keyed by the reveal reference suffix.
PERSON_SENSITIVE = {"ssn": mask_ssn, "ip_pin": mask_pin}
BANK_SENSITIVE = {"routing": mask_tail, "account": mask_tail}


def mask_household(household: Any) -> dict[str, Any]:
    people = []
    for person in household["people"]:
        p = dict(person)
        p["masked_fields"] = []
        for name, fn in PERSON_SENSITIVE.items():
            if p.get(name):
                p[name] = fn(p[name])
                p["masked_fields"].append(name)
        people.append(p)
    bank = dict(household["bank_account_for_refund_or_payment"])
    for name, fn in BANK_SENSITIVE.items():
        bank[name] = fn(bank.get(name))
    out = dict(household)
    out["people"] = people
    out["bank_account_for_refund_or_payment"] = bank | {"masked_fields": list(BANK_SENSITIVE)}
    return out


def mask_resolved(idx: Any, resolved: dict[str, Any]) -> dict[str, Any]:
    """Mask a resolved reference before it leaves the API.

    The resolver returns raw packet values (it serves internal joins). Anything that reaches a response
    — finding evidence, graph details, search results — must go through here, so a sensitive value is
    only ever seen through the logged reveal endpoint, whatever the caller's clearance.
    """
    out = dict(resolved)
    if out.get("kind") == "extracted_value" and out.get("exists"):
        ev = idx.values_by_id.get(out["ref"])
        if ev is not None and is_sensitive_value(ev):
            out["value"] = mask_extracted_value(ev)["value"]
            out["masked"] = True
    if isinstance(out.get("label"), str):
        out["label"] = mask_text(out["label"])
    if isinstance(out.get("value"), str):
        out["value"] = mask_text(out["value"])
    return out

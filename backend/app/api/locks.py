"""Write locks from the filing lifecycle (checked server-side by every write that could change the record).

- From submission on, the return's content (adjustments, judgments, sign-offs) is locked: what is with the
  agencies, or filed, must not move. Changes after filing are amendments.
- A frozen workpaper is read-only: only amendments and examination responses can still be written.
"""

from __future__ import annotations

from fastapi import HTTPException

from ..deps import Ctx
from ..services.filing import RETURN_LOCKED, STATE_LABEL


def _state(c: Ctx) -> str:
    return c.engagement.status if c.engagement.status in STATE_LABEL else "preparing"


def assert_return_editable(c: Ctx, what: str) -> None:
    s = _state(c)
    if s in RETURN_LOCKED:
        tail = "Changes to a filed return are made as an amendment." if s in ("filed", "frozen") else \
            "It is with the agencies; nothing that changes it can be recorded until they respond."
        raise HTTPException(409, f"The return is {STATE_LABEL[s]}: {what} is locked. {tail}")


def assert_not_frozen(c: Ctx, what: str) -> None:
    if _state(c) == "frozen":
        raise HTTPException(409, f"The workpaper is frozen: {what} is read-only. Only amendments and examination responses can be added.")

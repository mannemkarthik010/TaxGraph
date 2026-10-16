"""Load the supplied Miraflores packet exactly as delivered and make it immutable.

The packet is pipeline output. TaxProof never writes to it: the file is read once, hashed, and
deep-frozen so that any accidental mutation anywhere in the app raises immediately.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class FrozenDict(dict):
    """A dict that refuses mutation. Subclassing dict keeps it JSON-serializable for free."""

    __slots__ = ()

    def _immutable(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("Source packet is immutable; record changes in the workpaper layer instead.")

    __setitem__ = __delitem__ = _immutable  # type: ignore[assignment]
    clear = pop = popitem = setdefault = update = _immutable  # type: ignore[assignment]
    __ior__ = _immutable  # type: ignore[assignment]

    def __deepcopy__(self, memo: dict) -> dict:
        return thaw(self)

    def __copy__(self) -> dict:
        return dict(self)

    def __reduce__(self):  # pickling / deepcopy fallbacks produce plain dicts
        return (dict, (dict(self),))


def freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return FrozenDict({k: freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(freeze(v) for v in value)
    return value


def thaw(value: Any) -> Any:
    """Return a plain, mutable deep copy (for callers that need to build derived structures)."""
    if isinstance(value, dict):
        return {k: thaw(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [thaw(v) for v in value]
    return value


@dataclass(frozen=True)
class LoadedPacket:
    path: Path
    sha256: str
    size_bytes: int
    data: FrozenDict


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_packet(path: str | Path) -> LoadedPacket:
    p = Path(path)
    raw = p.read_bytes()
    data = json.loads(raw)
    _validate_shape(data)
    return LoadedPacket(path=p, sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw), data=freeze(data))


REQUIRED_SECTIONS = (
    "packet",
    "readme",
    "household",
    "documents",
    "extracted_values",
    "client",
    "firm",
    "prior_years",
    "tax_agency_records",
    "timeline",
    "engine_reference",
    "return_versions",
)


class PacketFormatError(ValueError):
    pass


def _validate_shape(data: Any) -> None:
    if not isinstance(data, dict):
        raise PacketFormatError("Packet root must be an object.")
    missing = [s for s in REQUIRED_SECTIONS if s not in data]
    if missing:
        raise PacketFormatError(f"Packet is missing sections: {', '.join(missing)}")
    if not data["return_versions"]:
        raise PacketFormatError("Packet has no return versions.")

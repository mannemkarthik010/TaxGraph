"""Read-only indexes over the frozen packet.

Everything here is derived, never stored back. Indexes are built once at startup (~3k values,
~1.9k lines across versions) and shared across requests.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from .loader import LoadedPacket


@dataclass
class PacketIndex:
    packet: LoadedPacket
    documents_by_id: dict[str, Any] = field(default_factory=dict)
    values_by_id: dict[str, Any] = field(default_factory=dict)
    values_by_document: dict[str, list[Any]] = field(default_factory=dict)
    versions_by_id: dict[str, Any] = field(default_factory=dict)
    return_lines_by_version: dict[str, dict[str, Any]] = field(default_factory=dict)
    return_lines_by_key: dict[str, dict[str, Any]] = field(default_factory=dict)
    # reverse edges: which lines (per version) consume a source ref / another line
    lines_by_source: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    lines_by_input: dict[tuple[str, str], list[str]] = field(default_factory=dict)
    timeline_by_id: dict[str, Any] = field(default_factory=dict)
    assets_by_id: dict[str, Any] = field(default_factory=dict)
    questions_by_id: dict[str, Any] = field(default_factory=dict)
    messages_by_id: dict[str, Any] = field(default_factory=dict)
    call_notes_by_id: dict[str, Any] = field(default_factory=dict)
    people_by_id: dict[str, Any] = field(default_factory=dict)
    staff_by_id: dict[str, Any] = field(default_factory=dict)
    prior_year_values: dict[str, dict[str, Any]] = field(default_factory=dict)
    agency_records: Any = None

    @property
    def data(self) -> Any:
        return self.packet.data

    @property
    def version_ids(self) -> list[str]:
        return [v["version"] for v in self.data["return_versions"]]

    @property
    def current_version(self) -> str:
        # README: the last computed version is the current return.
        return self.version_ids[-1]

    def line(self, version: str, key: str) -> Any | None:
        return self.return_lines_by_version.get(version, {}).get(key)


def build_index(packet: LoadedPacket) -> PacketIndex:
    d = packet.data
    idx = PacketIndex(packet=packet)

    for doc in d["documents"]:
        idx.documents_by_id[doc["id"]] = doc

    by_doc: dict[str, list[Any]] = defaultdict(list)
    for ev in d["extracted_values"]:
        idx.values_by_id[ev["id"]] = ev
        by_doc[ev["document_id"]].append(ev)
    idx.values_by_document = dict(by_doc)

    by_source: dict[str, list[tuple[str, str]]] = defaultdict(list)
    by_input: dict[tuple[str, str], list[str]] = defaultdict(list)
    by_key: dict[str, dict[str, Any]] = defaultdict(dict)
    for version in d["return_versions"]:
        vid = version["version"]
        idx.versions_by_id[vid] = version
        lines: dict[str, Any] = {}
        for line in version["lines"]:
            lines[line["key"]] = line
            by_key[line["key"]][vid] = line
            for src in line.get("sources", ()):
                by_source[src].append((vid, line["key"]))
            for inp in line.get("inputs", ()):
                by_input[(vid, inp)].append(line["key"])
        idx.return_lines_by_version[vid] = lines
        for asset in version.get("assets", ()):
            idx.assets_by_id.setdefault(asset["asset_id"], {})[vid] = asset
    idx.return_lines_by_key = dict(by_key)
    idx.lines_by_source = dict(by_source)
    idx.lines_by_input = dict(by_input)

    for asset in d["prior_years"].get("asset_records", ()):
        idx.assets_by_id.setdefault(asset["asset_id"], {})["prior"] = asset

    idx.timeline_by_id = {t["id"]: t for t in d["timeline"]}
    client = d["client"]
    idx.questions_by_id = {q["id"]: q for q in client.get("questionnaire", ())}
    idx.messages_by_id = {m["id"]: m for m in client.get("messages", ())}
    idx.call_notes_by_id = {c["id"]: c for c in client.get("call_notes", ())}
    idx.people_by_id = {p["id"]: p for p in d["household"]["people"]}
    idx.staff_by_id = {s["id"]: s for s in d["firm"]["staff"]}

    r24 = d["prior_years"].get("return_2024", {})
    labels = r24.get("line_labels", {})
    sources = r24.get("line_sources", {})
    idx.prior_year_values = {
        key: {"key": key, "value": value, "label": labels.get(key), "source": sources.get(key)}
        for key, value in r24.get("lines", {}).items()
    }
    idx.agency_records = d["tax_agency_records"]
    return idx

import copy
import json

import pytest

from app.config import settings
from app.packet.loader import FrozenDict, PacketFormatError, _validate_shape, load_packet, sha256_of, thaw
from app.packet.refs import json_pointer, resolve


def test_packet_parses_with_expected_counts(idx):
    d = idx.data
    assert d["packet"]["client_id"] == "CL-20417"
    assert len(d["documents"]) == 74
    assert len(d["extracted_values"]) == 3012
    assert idx.version_ids == ["v1", "v2", "v3"]
    assert idx.current_version == "v3"
    assert len(idx.documents_by_id) == 74
    assert len(idx.values_by_id) == 3012
    assert sum(len(v) for v in idx.values_by_document.values()) == 3012


def test_packet_is_deep_frozen(idx):
    with pytest.raises(TypeError):
        idx.data["household"]["filing_status"] = "single"
    with pytest.raises(TypeError):
        idx.values_by_id["ev-0315"]["value"] = 0
    with pytest.raises(TypeError):
        idx.data["documents"][0]["pages"][0].update({"printed_content": "x"})
    with pytest.raises(AttributeError):  # lists are tuples
        idx.data["documents"].append({})


def test_thaw_and_deepcopy_give_mutable_copies_without_touching_source(idx):
    copy_ = copy.deepcopy(idx.data["household"])
    copy_["filing_status"] = "changed"
    plain = thaw(idx.data["return_versions"][0]["summary"])
    plain["federal"]["total_tax"] = 0
    assert idx.data["household"]["filing_status"] == "married_filing_jointly"
    assert idx.data["return_versions"][0]["summary"]["federal"]["total_tax"] == 77200
    assert isinstance(idx.data["household"], FrozenDict)


def test_source_file_hash_matches_loaded_hash(idx):
    assert sha256_of(settings.packet_path) == idx.packet.sha256


def test_frozen_packet_serializes_to_identical_json(idx):
    original = json.loads(settings.packet_path.read_bytes())
    assert json.loads(json.dumps(idx.data)) == original


def test_shape_validation_rejects_incomplete_packets():
    with pytest.raises(PacketFormatError):
        _validate_shape({"packet": {}})
    with pytest.raises(PacketFormatError):
        _validate_shape([])


def test_load_packet_is_repeatable():
    a = load_packet(settings.packet_path)
    b = load_packet(settings.packet_path)
    assert a.sha256 == b.sha256 and a.size_bytes == b.size_bytes


# ---- evidence resolution ---------------------------------------------------------------------------

@pytest.mark.parametrize("ref,kind", [
    ("ev-0315", "extracted_value"),
    ("D23", "document"),
    ("doc:D30#page32", "page"),
    ("qa-14", "client_answer"),
    ("msg-10", "client_message"),
    ("call-01", "call_note"),
    ("py:/return_2024/lines/F8606.14", "prior_year_value"),
    ("py:/carryovers_into_2025/capital_loss_long", "prior_year_value"),
    ("agency:/notices/1", "agency_record"),
    ("agency:/efile", "agency_record"),
    ("asset:SAC-BLDG", "asset"),
    ("household:theo", "household_member"),
    ("ref:param.mileage_rate", "engine_parameter"),
    ("ref:fx.SEK.2025_year_end", "fx_rate"),
    ("timeline:extension-2026-04-14", "timeline_event"),
    ("v2", "return_version"),
    ("line:v3:SchC.44a", "return_line"),
    ("SchC.I", "return_line"),
    ("R-MILEAGE-PAGE-TOTALS", "engine_rule"),
])
def test_resolver_handles_every_reference_format(idx, ref, kind):
    r = resolve(idx, ref)
    assert r.kind == kind
    assert r.exists, ref


def test_resolver_reports_missing_refs(idx):
    assert not resolve(idx, "ev-9999").exists
    assert not resolve(idx, "doc:D23#page9").exists
    assert not resolve(idx, "py:/nope").exists
    assert resolve(idx, "garbage").kind == "unknown"


def test_extracted_value_resolves_to_its_document_page(idx):
    r = resolve(idx, "ev-0315")
    assert (r.document_id, r.page, r.value) == ("D23", 2, 3700)


def test_json_pointer_escapes():
    assert json_pointer({"a/b": {"~c": 1}}, "/a~1b/~0c") == 1


def test_every_reference_in_lines_diagnostics_and_timeline_resolves(idx):
    """The packet's own citations must all land somewhere, or the graph has holes."""
    unresolved = []
    for v in idx.data["return_versions"]:
        for line in v["lines"]:
            for ref in list(line.get("sources", ())) + list(line.get("inputs", ())):
                if not resolve(idx, ref, v["version"]).exists:
                    unresolved.append((v["version"], line["key"], ref))
        for dg in v["diagnostics"]:
            for ref in dg["refs"]:
                if not resolve(idx, ref, v["version"]).exists:
                    unresolved.append((v["version"], dg["code"], ref))
    for t in idx.data["timeline"]:
        for ref in t["refs"]:
            if not resolve(idx, ref).exists:
                unresolved.append(("timeline", t["id"], ref))
    assert unresolved == []

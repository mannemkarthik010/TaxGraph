from app.services.areas import AREAS, COMPUTATION, area_for_line
from app.services.returns import line_detail, line_groups, list_lines, return_summary
from app.services.variance import compute_variance


def test_line_inputs_reference_lines_in_the_same_version(idx):
    for vid, lines in idx.return_lines_by_version.items():
        for line in lines.values():
            for inp in line.get("inputs", ()):
                assert inp in lines, f"{vid}:{line['key']} input {inp} missing"


def test_reverse_source_index_finds_consumers(idx):
    # ev-0315 (D23 page 2 total) is consumed by Schedule C business miles in every version.
    consumers = idx.lines_by_source["ev-0315"]
    assert ("v3", "SchC.44a") in consumers
    assert {v for v, _ in consumers} == {"v1", "v2", "v3"}


def test_line_detail_shows_rule_sources_and_consumers(idx):
    d = line_detail(idx, "v3", "SchC.44a")
    assert d["value"] == 11800
    assert d["rule"] == "R-MILEAGE-PAGE-TOTALS"
    assert [s["ref"] for s in d["sources"]] == ["ev-0226", "ev-0315", "ev-0477", "ev-0404"]
    assert {s["page"] for s in d["sources"]} == {1, 2, 3, 4}
    assert sum(s["value"] for s in d["sources"]) == 11800
    assert any(u["key"] == "SchC.9" for u in d["used_by"])


def test_used_by_is_the_inverse_of_inputs(idx):
    v = "v3"
    for key, line in idx.return_lines_by_version[v].items():
        for inp in line.get("inputs", ()):
            assert key in idx.lines_by_input[(v, inp)]


def test_line_detail_unknown_key_returns_none(idx):
    assert line_detail(idx, "v3", "NOPE.1") is None


def test_every_line_maps_to_exactly_one_area(idx):
    keys = {a.key for a in AREAS} | {COMPUTATION}
    for line in idx.data["return_versions"][-1]["lines"]:
        assert area_for_line(line) in keys
    groups = line_groups(idx, "v3")
    assert sum(g["line_count"] for g in groups) == len(idx.data["return_versions"][-1]["lines"])


def test_list_lines_filters_and_paginates(idx):
    page = list_lines(idx, "v3", form="F8949", limit=50)
    assert page["total"] == 302 and len(page["items"]) == 50
    hits = list_lines(idx, "v3", q="business miles")
    assert [i["key"] for i in hits["items"]] == ["SchC.44a"]


def test_summary_matches_supplied_engine_and_prior_year(idx):
    s = return_summary(idx, "v3")
    by = {(h["jurisdiction"], h["field"]): h for h in s["headlines"]}
    assert by[("federal", "total_tax")]["value"] == 81962
    assert by[("federal", "total_tax")]["prior_year"] == 37557
    assert by[("federal", "total_tax")]["variance_flag"] is True
    assert by[("federal", "balance_due")]["prior_year"] == -393  # 2024 was an overpayment
    assert by[("california", "balance_due")]["value"] == -8256


def test_variance_rule_needs_both_thresholds():
    assert compute_variance(1500, 1000, 10, 1000).flagged is False   # +50% but only +500
    assert compute_variance(105000, 100000, 10, 1000).flagged is False  # +5000 but only 5%
    assert compute_variance(130000, 100000, 10, 1000).flagged is True
    assert compute_variance(5000, 0, 10, 1000).flagged is True        # new item
    assert compute_variance("Yes", "No", 10, 1000).flagged is False   # text lines never flag

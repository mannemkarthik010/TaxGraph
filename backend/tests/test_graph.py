from app.services.graph import FLOW, GraphView, closure, footprint, get_graph, impact, subgraph
from tests.conftest import as_user

PREPARER, REVIEWER, PARTNER, CLIENT = "st-01", "st-02", "st-03", "cu-01"


def _view(idx):
    return GraphView(get_graph(idx))


# ---- construction ----------------------------------------------------------------------------------

def test_graph_has_every_packet_object(idx):
    g = get_graph(idx)
    kinds = {}
    for n in g.nodes.values():
        kinds[n.kind] = kinds.get(n.kind, 0) + 1
    assert kinds["Document"] == 74 and kinds["ExtractedValue"] == 3012 and kinds["Page"] == 199
    assert kinds["ReturnLine"] == sum(len(v["lines"]) for v in idx.data["return_versions"])
    assert kinds["ClientAnswer"] == 45 + 10 + 1
    assert kinds["TimelineEvent"] == len(idx.data["timeline"])


def test_every_line_source_and_input_is_an_edge(idx):
    g = get_graph(idx)
    for v in idx.data["return_versions"]:
        for line in v["lines"]:
            lid = f"line:{v['version']}:{line['key']}"
            into = {(e.src, e.type) for e in g.in_edges[lid]}
            for inp in line.get("inputs", ()):
                assert (f"line:{v['version']}:{inp}", "INPUT_TO") in into
            for src in line.get("sources", ()):
                assert (src, "SOURCE_OF") in into, (lid, src)


def test_every_value_hangs_off_its_page_and_document(idx):
    g = get_graph(idx)
    for ev in idx.data["extracted_values"][::97]:
        page = f"doc:{ev['document_id']}#page{ev['page']}"
        assert any(e.src == page and e.type == "SOURCE_OF" for e in g.in_edges[ev["id"]])
        assert any(e.src == ev["document_id"] for e in g.in_edges[page])


def test_analysis_becomes_edges(idx):
    g = get_graph(idx)
    edges = {(e.src, e.dst, e.type) for es in g.out_edges.values() for e in es if e.type not in FLOW}
    assert ("doc:D23#page3", "doc:D23#page2", "DUPLICATE_OF") in edges
    assert ("D10", "D09", "DUPLICATE_OF") in edges
    assert ("D31", "D30", "SUPERSEDES") in edges
    assert ("ev-1080", "household:theo", "CONFLICTS_WITH") in edges
    assert ("ev-1045", "doc:D62#page1", "CONFLICTS_WITH") in edges
    assert ("line:v3:SchC.44a", "rule:R-MILEAGE-PAGE-TOTALS", "CALCULATED_FROM") in edges
    assert ("py:/return_2024/lines/SchC.9", "line:v3:SchC.9", "RELATED_TO") in edges


def test_sensitive_values_are_masked_in_graph(idx):
    n = get_graph(idx).nodes["ev-1080"]
    assert "666-74" not in str(n.value) and str(n.value).endswith("3390")


# ---- prove it --------------------------------------------------------------------------------------

def test_prove_mileage_reaches_the_duplicate_pages(idx):
    view = _view(idx)
    sg = subgraph(view, "line:v3:SchC.9", "up", depth=6)
    ids = {n["id"] for n in sg["nodes"]}
    assert {"line:v3:SchC.44a", "ev-0315", "ev-0404", "doc:D23#page2", "doc:D23#page3", "D23",
            "ref:param.mileage_rate"} <= ids
    assert any(e["type"] == "DUPLICATE_OF" and e["src"] == "doc:D23#page3" for e in sg["edges"])
    levels = {n["id"]: n["level"] for n in sg["nodes"]}
    assert levels["line:v3:SchC.9"] == 0 and levels["line:v3:SchC.44a"] == 1 and levels["D23"] == 4


def test_footprint_is_complete_even_when_the_picture_is_truncated(idx):
    view = _view(idx)
    sg = subgraph(view, "line:v3:F1040.24", "up", depth=2, max_children=5)
    fp = footprint(idx, view, "line:v3:F1040.24")
    assert len(sg["nodes"]) < 60
    assert fp["lines"] > 500 and fp["values"] > 1800 and len(fp["documents"]) > 40
    assert {"document_id": "D23", "pages": [2, 3]} in fp["duplicate_pages_in_evidence"]
    flagged = {f["ref"] for f in fp["flags"]}
    # The ambiguous handwritten gift and the RSU lots whose blank basis became 0 both feed total tax…
    assert {"ev-1049", "ev-0498"} <= flagged
    # …while the transposed child-care provider ID only feeds Form 2441 detail lines.
    assert "ev-1045" not in flagged


def test_truncation_groups_and_expand(idx):
    view = _view(idx)
    small = subgraph(view, "line:v3:F8949.A.total", "up", depth=1, max_children=3)
    assert small["groups"] and small["groups"][0]["parent"] == "line:v3:F8949.A.total"
    hidden = small["groups"][0]["count"]
    opened = subgraph(view, "line:v3:F8949.A.total", "up", depth=1, max_children=3, expand={"line:v3:F8949.A.total"})
    assert not [g for g in opened["groups"] if g["parent"] == "line:v3:F8949.A.total"]
    assert len(opened["nodes"]) >= len(small["nodes"]) + hidden


def test_trace_document_down_to_final_tax(idx):
    dist = closure(_view(idx), "D23", "down")
    assert "line:v3:F1040.24" in dist and "line:v3:F540NR.64" in dist
    assert dist["line:v3:SchC.44a"] < dist["line:v3:F1040.24"]


def test_impact_radius_of_duplicate_page_total(idx):
    imp = impact(idx, _view(idx), "ev-0404", "v3")
    keys = {l["key"] for r in imp["rings"] for l in r["lines"]}
    assert {"SchC.44a", "SchC.9", "SchC.28", "SchC.31", "F1040.24", "F540NR.64"} <= keys
    assert imp["rings"][0]["distance"] == 1 and [l["key"] for l in imp["rings"][0]["lines"]] == ["SchC.44a"]
    assert {h["key"] for h in imp["headlines"]} >= {"F1040.11", "F1040.24", "F1040.37", "F540NR.64"}
    assert set(imp["by_version"]) == {"v1", "v2", "v3"} and imp["version"] == "v3"
    assert all(l["id"].startswith("line:v3:") for r in imp["rings"] for l in r["lines"])


def test_impact_of_terminal_line_is_empty(idx):
    assert impact(idx, _view(idx), "line:v3:F1040.38", "v3")["affected_lines"] == 0


# ---- API -------------------------------------------------------------------------------------------

def test_prove_api_accepts_bare_keys_and_includes_footprint(client):
    r = client.get("/api/graph/prove?ref=SchC.9&depth=5", headers=as_user(PREPARER)).json()
    assert r["root"] == "line:v3:SchC.9" and r["footprint"]["values"] == 4
    assert client.get("/api/graph/prove?ref=NOPE.1", headers=as_user(PREPARER)).status_code == 404
    assert client.get("/api/graph/prove?ref=SchC.9&version=v9", headers=as_user(PREPARER)).status_code == 404


def test_trace_and_impact_api(client):
    t = client.get("/api/graph/trace?ref=D23&depth=3", headers=as_user(REVIEWER)).json()
    assert t["direction"] == "down" and t["impact"]["affected_lines"] > 50
    i = client.get("/api/graph/impact?ref=ev-0315", headers=as_user(CLIENT)).json()  # clients may see structure
    assert i["headlines"]


def test_verifications_join_the_graph_for_staff_only(client):
    client.post("/api/verifications", headers=as_user(PREPARER),
                json={"target_ref": "ev-0477", "method": "agreed_to_source_document"})
    staff = client.get("/api/graph/prove?ref=SchC.44a&depth=3", headers=as_user(REVIEWER)).json()
    assert any(e["type"] == "VERIFIED_BY" and e["src"] == "ev-0477" for e in staff["edges"])
    assert staff["footprint"]["verified_values"] >= 1
    client_view = client.get("/api/graph/prove?ref=SchC.44a&depth=3", headers=as_user(CLIENT)).json()
    assert not any(e["type"] == "VERIFIED_BY" for e in client_view["edges"])


def test_human_links(client):
    post = lambda u, b: client.post("/api/graph/links", headers=as_user(u), json=b)  # noqa: E731
    r = post(PREPARER, {"src_ref": "msg-06", "dst_ref": "D40", "type": "RELATED_TO",
                        "note": "Client found the 2023 Woodworks K-1 in family papers"})
    assert r.status_code == 201
    link_id = r.json()["id"]
    assert post(PREPARER, {"src_ref": "msg-06", "dst_ref": "D40", "type": "RELATED_TO", "note": "again"}).status_code == 409
    assert post(PREPARER, {"src_ref": "msg-06", "dst_ref": "msg-06", "type": "RELATED_TO", "note": "x"}).status_code == 422
    assert post(PREPARER, {"src_ref": "msg-06", "dst_ref": "D99", "type": "RELATED_TO", "note": "x"}).status_code == 404
    assert post(PREPARER, {"src_ref": "msg-06", "dst_ref": "D40", "type": "INPUT_TO", "note": "x"}).status_code == 422
    assert post(CLIENT, {"src_ref": "msg-06", "dst_ref": "D40", "type": "CONFIRMED_BY", "note": "x"}).status_code == 403
    # bare line keys normalise to the current version; links to any resolvable ref get a node
    lk = post(REVIEWER, {"src_ref": "SchE.28A", "dst_ref": "py:/basis_records/scorp_lindqvist_family_woodworks/0",
                         "type": "RELATED_TO", "note": "Basis roll-forward support"})
    assert lk.status_code == 201 and lk.json()["src_ref"] == "line:v3:SchE.28A"

    node = client.get("/api/graph/node?ref=D40", headers=as_user(PARTNER)).json()
    assert any(e["type"] == "RELATED_TO" and e["other"] == "msg-06" and e["origin"] == "workpaper" for e in node["incoming"])
    basis = client.get("/api/graph/node?ref=py:/basis_records/scorp_lindqvist_family_woodworks/0",
                       headers=as_user(PARTNER)).json()
    assert basis["kind"] == "PriorYearValue"

    retire = lambda u: client.post(f"/api/graph/links/{link_id}/retire", headers=as_user(u), json={"reason": "wrong K-1"})  # noqa: E731
    assert retire("st-04").status_code == 403
    assert retire(REVIEWER).status_code == 200
    assert retire(REVIEWER).status_code == 409
    node = client.get("/api/graph/node?ref=D40", headers=as_user(PARTNER)).json()
    assert not any(e["origin"] == "workpaper" and e["other"] == "msg-06" for e in node["incoming"])
    actions = {e["action"] for e in client.get("/api/audit/events?limit=500", headers=as_user(PARTNER)).json()}
    assert {"evidence_link.created", "evidence_link.retired"} <= actions


def test_line_refs_keep_their_own_version(client):
    """Regression: impact/trace for a v1 line used to default to v3 and report nothing affected."""
    h = as_user(REVIEWER)
    for v in ("v1", "v2", "v3"):
        imp = client.get(f"/api/graph/impact?ref=line:{v}:SchC.44a", headers=h).json()
        assert imp["version"] == v and imp["affected_lines"] > 90, v
        assert all(l["id"].startswith(f"line:{v}:") for r in imp["rings"] for l in r["lines"])
        assert {x["key"] for x in imp["headlines"]} >= {"F1040.24", "F540NR.64"}
        tr = client.get(f"/api/graph/trace?ref=line:{v}:SchC.44a", headers=h).json()
        assert tr["version"] == v and tr["impact"]["version"] == v
        assert tr["impact"]["affected_lines"] == imp["affected_lines"]
        pr = client.get(f"/api/graph/prove?ref=line:{v}:SchC.44a", headers=h).json()
        assert pr["version"] == v and pr["root"] == f"line:{v}:SchC.44a"
    # an explicit version agreeing with the line is fine; a contradicting one is refused, not ignored
    assert client.get("/api/graph/impact?ref=line:v1:SchC.44a&version=v1", headers=h).status_code == 200
    for path in ("impact", "trace", "prove", "node"):
        r = client.get(f"/api/graph/{path}?ref=line:v1:SchC.44a&version=v3", headers=h)
        assert r.status_code == 422, path


def test_non_line_refs_are_read_in_the_requested_version(client):
    h = as_user(REVIEWER)
    for v in ("v1", "v2", "v3"):
        imp = client.get(f"/api/graph/impact?ref=ev-0315&version={v}", headers=h).json()
        assert imp["version"] == v and imp["affected_lines"] > 90
        assert all(l["id"].startswith(f"line:{v}:") for r in imp["rings"] for l in r["lines"])
    # bare keys resolve in the requested version too
    assert client.get("/api/graph/prove?ref=SchC.44a&version=v1", headers=h).json()["root"] == "line:v1:SchC.44a"
    # with no version, the current return is used — and the response says which
    assert client.get("/api/graph/impact?ref=ev-0315", headers=h).json()["version"] == "v3"


def test_impact_for_lines_that_exist_only_in_some_versions(client, idx):
    added = [c["key"] for c in idx.versions_by_id["v3"]["changes_from_previous"] if c["change"] == "added"]
    assert added  # e.g. SchB.1.8 / SchE.28B arrive with the Ridgeline K-1 in v3
    h = as_user(REVIEWER)
    assert client.get(f"/api/graph/impact?ref=line:v3:{added[0]}", headers=h).status_code == 200
    assert client.get(f"/api/graph/impact?ref=line:v2:{added[0]}", headers=h).status_code == 404


def test_columns_stay_legible_and_expand_overrides_the_budget(idx):
    view = _view(idx)
    root = "line:v3:F8949.A.total"
    sg = subgraph(view, root, "up", depth=4, max_children=8, max_per_level=14)
    per_level = {}
    for n in sg["nodes"]:
        if not n["annotation"]:
            per_level[n["level"]] = per_level.get(n["level"], 0) + 1
    assert max(per_level.values()) <= 14
    # nothing is lost: every hidden neighbour is counted in some group
    lot = next(g["parent"] for g in sg["groups"] if g["parent"] != root)
    opened = subgraph(view, root, "up", depth=4, max_children=8, max_per_level=14, expand={lot})
    lot_sources = {e.src for e in view.incoming(lot) if e.type in FLOW}
    assert lot_sources <= {n["id"] for n in opened["nodes"]}
    assert not any(g["parent"] == lot for g in opened["groups"])



def test_workpaper_overlay_nodes_are_valid_roots(client):
    """Regression: a verification node opened in the inspector returned 404 from Prove It / trace / impact."""
    v = client.post("/api/verifications", headers=as_user(PREPARER), json={"target_ref": "ev-0404", "method": "agreed_to_source_document"}).json()
    ref = f"verification:{v['id']}"
    for ep in ("node", "prove", "trace", "impact"):
        assert client.get(f"/api/graph/{ep}", params={"ref": ref}, headers=as_user(REVIEWER)).status_code == 200, ep
    prove = client.get("/api/graph/prove", params={"ref": ref}, headers=as_user(REVIEWER)).json()
    assert any(n["id"] == ref for n in prove["nodes"])                            # the root is in the picture
    assert any(e["type"] == "VERIFIED_BY" and e["src"] == "ev-0404" for e in prove["edges"])
    # clients have no workpaper overlay: the node does not exist for them
    assert client.get("/api/graph/prove", params={"ref": ref}, headers=as_user(CLIENT)).status_code == 404
    assert client.get("/api/graph/prove", params={"ref": "verification:99999"}, headers=as_user(REVIEWER)).status_code == 404
    # a resolvable packet ref with no graph node yet is still a valid root
    assert client.get("/api/graph/prove", params={"ref": "py:/basis_records/partnership_ridgeline"},
                      headers=as_user(REVIEWER)).status_code == 200


def test_prior_year_counterpart_is_the_same_on_every_screen(idx):
    """Regression: the summary showed 12,520 for F540NR.64 while the line drawer showed no prior year."""
    from app.services.returns import line_detail
    from app.services.schedules import prior_value, tax_computation
    g = get_graph(idx)
    for key in idx.return_lines_by_version["v3"]:
        pv = prior_value(idx, key)
        drawer = line_detail(idx, "v3", key)["prior_year"]
        assert (drawer["value"] if drawer else None) == (pv["value"] if pv else None), key
        if pv:
            assert any(e.src == f"py:/return_2024/lines/{pv['key']}" and e.type == "RELATED_TO"
                       for e in g.in_edges[f"line:v3:{key}"]), key
    summary = {r["key"]: r["prior_year"] for juris in ("federal", "california") for r in tax_computation(idx, "v3")[juris]}
    for key, value in summary.items():
        drawer = line_detail(idx, "v3", key)["prior_year"]
        assert (drawer["value"] if drawer else None) == value, key
    assert line_detail(idx, "v3", "F540NR.64")["prior_year"]["key"] == "CA540.64"
    assert line_detail(idx, "v3", "F540NR.32")["prior_year"] is None

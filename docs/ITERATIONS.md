# Iteration log

## Iteration 1: Foundation ✅

**Goal:** application shell, an immutable source layer and a mutable workpaper layer, real roles.

### Delivered
- **Packet layer.** The packet is loaded once, SHA-256 hashed and deep-frozen (`FrozenDict` and tuples,
  so any write raises). Indexes: documents, values (by id and by document), versions, lines (by version
  and by key), reverse edges (`lines_by_source`, `lines_by_input`), timeline, assets, questionnaire,
  messages, call notes, people, staff, prior-year values and agency records.
- **Universal reference resolver** for every format in `readme.reference_formats`, plus
  `line:<version>:<key>` and `rule:<id>`. A test checks that every source, input, diagnostic ref
  and timeline ref in the packet resolves (it does).
- **Workpaper DB** (PostgreSQL via Alembic, SQLite compatible): `engagements`, `users`,
  `engagement_assignments`, `workpaper_areas`, `workpaper_notes`, `audit_events`, `access_logs`.
  Seeding is idempotent. If the packet's hash changes on disk, that is recorded in the audit log.
- **Hash-chained audit log.** Each event hashes its content plus the previous hash, so `/api/audit/verify`
  detects any edited or deleted row. Permission denials are audited too.
- **Roles enforced on the server.** The switcher selects an acting user and the `X-TaxProof-User` header
  identifies them. Permissions come from a matrix in `security/roles.py`. The independence rule
  (`assert_independent`) is implemented and tested, ready for sign-offs in Iteration 7.
- **Sensitive data.** SSNs, IP PINs, bank and account numbers, 8879 signature PINs, and SSN/IBAN/account
  patterns inside free text are masked for everyone. Cleared staff and the clients can reveal one
  field at a time. Every reveal, granted or denied, is written to `access_logs` and the audit chain.
- **UI** (Next.js, Tailwind, shadcn/ui), with `g`+letter keyboard navigation:
  - *Overview*: federal and CA headlines, the 2024 comparison using the firm's variance rule
    (>10% and >$1,000), assurance posture, packet integrity, household with masked fields and logged
    reveal, the CA→TX residency bar, team, deadlines, and the 11 tax areas.
  - *Return*: v1/v2/v3 selector, area → form navigation, search, pagination (F8949 has 302 lots).
    The line drawer shows the engine rule, inputs, cited evidence (doc/page/confidence/read-as), what
    the line flows into, values across versions, 2024 value and variance, engine diagnostics labelled
    **ENGINE**, and workpaper notes.
  - *Evidence*: document index with used / not used / superseded / partial / corrected statuses.
  - *Review*: notes and review notes on any reference. Review notes block filing.
  - *Timeline*: the season with a "now = v3" marker. Later events are dimmed as replay material.
  - *Filing*: lifecycle (static), current blockers (open blocking review notes, live), required steps.
  - *Firm*: staff and clearance, standards, audit trail with chain verification, access log.

### Tests (65, `backend/tests`)
packet parsing and immutability · hash stability · reference resolution (every packet ref) ·
return-line input/consumer relationships · area mapping · summary vs prior year · variance rule ·
masking (household, printed content, IBAN, IP PIN, signature PINs, extracted values) · role matrix ·
reveal permissions and logging · note persistence and role rules · reference validation ·
audit chain verification and tamper detection · source packet unchanged after all API workflows.

### Limitations
- Authentication is simulated (header-based acting user). RBAC is still server-side.
- Area sign-off states exist in the schema but nothing changes them yet (Iteration 7).
- Placeholder panels are labelled "Planned — Iteration N" and do not pretend to work.

### Things already noticed for later iterations (not hard-coded)
- `SchC.44a = 11,800` sums D23 page totals 2,600 + 3,700 + 3,700 + 1,800. Pages 2 and 3 are the same May–Aug sheet.
- `SchC.1 = 163,700` adds "unmatched" 1099-K receipts to books revenue of 151,300. $12,400 may be counted twice (Paywell vs Atlas).
- Theo's SSN is `666-74-3309` in the organizer but `666-74-3390` on his card (D71/ev-0012). msg-10 says the organizer number was mistyped. This later causes the e-file rejection.

## Iteration 2: Evidence Explorer ✅

**Goal:** let a CPA open any document, see the page, click a value, find it on the page, verify it,
and see every place it was used.

### Delivered
- **Deterministic evidence checks** (`services/evidence.py`). These are computed once per packet hash
  (about 0.3s) and never trust extraction confidence:
  - *Read vs printed*: each money, number, date and text value is compared with the page's
    `printed_content`. The result is `PRINTED_MISMATCH` (conflict), `VALUE_NOT_PRINTED` or
    `ZERO_NOT_PRINTED` (needs review), or `NO_VALUE`.
  - *Identity*: an SSN that matches no SSN in the organizer is flagged `IDENTITY_MISMATCH`.
  - *Low confidence*: below 0.80.
  - *Duplicate pages*: two pages count as one sheet only when they have the same readings or the same
    printed numbers **and** near-identical text. Brokerage pages built from a template are not flagged.
  - *Duplicate / corrected documents*: same family (type, owner, year) with ≥90% identical readings.
    If one is marked CORRECTED, the pair is a correction rather than a duplicate.
  - *Locating values in the text*: finds where each value sits in the printed text and uses the words
    just before it to tell repeated amounts apart (e.g. W-2 boxes 3 and 5 both print 112,000.00).
    2,961 of 3,012 values are located; the rest are checkboxes or values that aren't printed.
- **Document statuses** with a reason for each: Used, Unused (and why), Superseded (by what), Corrected,
  Partial extraction, Not extracted, Conflict, Duplicate, Needs review.
- **Verification workflow**:
  - New `verifications` table (migration `0002`), recording target, method, note, evidence refs,
    acknowledged flags, user, role and timestamp.
  - Methods: agreed to source document, recalculated, confirmed with client, agreed to prior year,
    agreed to agency record, agreed to third-party evidence.
  - Rules:
    - A bare "agreed to source" tick is allowed only on a clean value.
    - Every other method needs a note, and so does any flagged value; the flags are recorded as acknowledged.
    - Client confirmation must cite a `qa-`/`msg-`/`call-` reference.
    - A verification is withdrawn rather than deleted, by its verifier or a reviewer.
  - Clients can't see or record verifications. Every action is written to the audit chain.
- **Reverse tracing**:
  - *Value*: return lines in every version, engine diagnostics, and 2024 lines it supports.
  - *Document*: the current-version lines its values feed, its timeline references, and why it
    wasn't used if it wasn't.
- **UI**:
  - Three panes: document index (search, status filters with counts) · simulated page · value panel.
  - The page renderer (`PageSurface`) takes the background and highlights as inputs, so a real page
    image can replace the simulated text without other changes. Highlights come from text spans plus
    the packet's synthetic `position` box, which can be toggled off.
  - Colours: red = conflict, amber = review, green = verified.
  - Duplicate pages are marked in the page strip.
  - Keys: ←/→ change page, j/k move between values.
  - The Return drawer now links each cited source to its exact page and value, shows TaxProof's checks
    next to the engine's citation, and lets you verify the line itself (e.g. "Recalculated").

### Confident mistakes this iteration surfaces (none hard-coded)
| Where | What | How it surfaced |
|---|---|---|
| D62 ev-1045 → F2441.1b | Provider tax ID read `74-3829516`; page prints `74-3829156` (conf 0.97) | `PRINTED_MISMATCH` |
| D64 ev-1049 | Handwritten `$?,500.00` read as 1,500 | `PRINTED_MISMATCH` + low confidence |
| D28 ev-0498/0516/0525 | RSU basis printed "(not reported)" recorded as 0 | `VALUE_NOT_PRINTED` |
| D71 ev-1080, D06 ev-0012 | Theo's SSN `…3390` on card and 2024 return vs `…3309` in organizer | `IDENTITY_MISMATCH` |
| D23 pages 2–3 | Same May–Aug mileage sheet scanned twice | duplicate page |
| D10 | Phone photo of the D09 W-2 | duplicate document |
| D30 → D31 | Corrected Meridian 1099 | corrected pair, superseded status |

### Tests (85 total, 20 new in `test_evidence.py`)
value checks (match, misread, blank→0, transposition, dates, identity, confidence) · the packet's
confident mistakes · page duplicates (D23 only; template pages excluded) · duplicate and corrected
documents · locating values and telling repeated amounts apart · document statuses · reverse tracing ·
document/value API (masked text and spans) · verification rules, roles, withdrawal, audit.

### Review follow-ups (after the Iteration 2 review)
- **Location box lines up with the page.** In the simulated renderer the box is measured from where the
  value's text span is actually drawn, so it always surrounds the printed value (checked in the
  browser: the box sits 3px outside the highlighted characters). The packet's synthetic `position`
  is shown in the value panel as "recorded position" and is what an image renderer would use.
  If a value can't be found in the printed text, the page says so instead of drawing a misleading box.
- **Printed layout.** The packet's `printed_content` has no line breaks; each page is one run of
  items. The renderer preserves whitespace (`pre-wrap`) and by default draws each item (`;`, `|`,
  sentence end) on its own line, so a W-2 reads box by box and the mileage log trip by trip.
  Only the space after a separator becomes a line break; highlight offsets still index the
  unmodified text. "As one block" shows the text exactly as delivered.
- **Evidence must match the method.** "Confirmed with client" accepts only client answers, messages
  or call notes. "Agreed to agency record" accepts only agency records, and "agreed to prior year"
  only prior-year sources. Those three require at least one reference. Mixed lists containing a
  wrong kind are refused.
- **PostgreSQL verified.** The full suite runs on PostgreSQL via
  `TAXPROOF_TEST_DATABASE_URL=…/taxproof_test` (the schema is rebuilt from migrations each run):
  86/86 pass, the same as on SQLite.
- **Browser click-through completed:**
  - Evidence: D23 page 2 → value → box; D08 W-2 layout; D62 conflict and verification.
  - "Confirmed with client" citing D08 is refused in the UI.
  - Return drawer → source link → D23 page 3 with the value boxed.
  - Client role: pages are visible, verifications are hidden.

### Limitations
- Flags are evidence statuses. Turning them into findings with tax impact is Iteration 5.
- Itemized layout is a display heuristic for one-line packet text; real scans would use the image renderer.

## Iteration 3: Evidence Graph + Prove It ✅

**Goal:** make every important number explain itself, and every source show everything it touches.

### Delivered
- **Evidence graph** (`services/graph.py`), built from the packet once per packet hash (about 0.4s):
  5,527 nodes and 13,613 edges. Node ids are the packet's own references, so workpaper records join
  without any id mapping. No graph database: adjacency lists in memory, and links people create are
  stored in PostgreSQL.
  - *Nodes:* Document, Page, ExtractedValue, ReturnLine (all three versions), CalculationRule,
    EngineParameter, EngineDiagnostic, PriorYearValue, AgencyRecord, ClientAnswer
    (questionnaire/message/call), HouseholdMember, Asset, TimelineEvent, plus a per-request overlay
    of Verification nodes. Adjustment, Judgment and Signoff nodes join in Iterations 6–7, using the
    same reference mechanism.
  - *Evidence-flow edges:* Document → Page → ExtractedValue → ReturnLine
    (`SOURCE_OF`), and ReturnLine → ReturnLine (`INPUT_TO`).
  - *Annotation edges:* `CALCULATED_FROM` (rule), `VERIFIED_BY`, `CONFIRMED_BY`, `SUPERSEDES`
    (D31→D30), `DUPLICATE_OF` (D23 p3→p2, D10→D09), `CONFLICTS_WITH` (misreads → page; Theo's card
    and 2024 return → household), and `RELATED_TO` (2024 counterpart lines, diagnostics, timeline).
    Iteration 2's evidence checks become edges here, so they show up wherever a trace passes through them.
- **Prove It** (`/prove`, upstream): the result on the left, then computation, intermediate lines,
  extracted values and pages, with documents on the right. Large fan-ins collapse into "N more" groups.
  Click a group, or double-click a node, to drill in. Headline results open at depth 2; the depth
  slider goes to 10.
- **Proof footprint**: a complete, untruncated summary of everything a number rests on:
  - lines, values and documents
  - verification coverage
  - duplicate pages in the evidence
  - value conflicts and review flags, each linked to its page
- **Where it goes** (downstream): any document, page or value traced forward to the final tax.
- **Impact radius**: every line in the chosen version that would need recomputing, grouped ring by
  ring (hops along the engine's input chain), with the headline results reached, a breakdown by area,
  and the other versions it feeds. It is explicitly structural; tax estimates come in Iteration 6.
- **Node inspector**: properties, relationships, re-root from any node (Prove it / Where it goes /
  Impact), a link out to the Return or Evidence screen, and **human links**. A new `evidence_links`
  table (migration `0003`) records related to / confirmed by / conflicts with / supersedes /
  duplicate of, with a required note. Links are retired, never deleted, and audited. Clients can view
  graph structure but not internal verifications or links.
- **Entry points**:
  - "Prove it", "Where it goes" and "Impact radius" on every return line drawer
  - "Prove it" on each overview headline
  - "Trace this document to the final tax" and value trace and impact links in Evidence
  - a "Prove any number" box in the header (accepts `SchC.9`, `F1040.24`, `ev-0315`, `D23`, `doc:D23#page3`)

### What the graph shows on this packet
- `SchC.9` (8,260) ← `SchC.44a` (11,800) × mileage rate ← four page totals ← D23 pages 1–4, with
  page 3 drawn as *duplicate of* page 2. The footprint says so even if you never open the page.
- Federal total tax rests on 521 lines, 1,872 extracted values and 51 documents. Its footprint
  includes the ambiguous handwritten $?,500 gift (D64) and the RSU lots whose unreported basis was
  read as 0 (D28). The transposed child-care provider ID (D62) does **not** reach total tax; it only
  feeds Form 2441 detail lines. That distinction is something the graph can show and a flat list cannot.
- Changing D23 page 3 would force recomputation of 95 v3 lines, reaching federal AGI, taxable
  income, total tax and balance due, and California AGI, tax and overpayment.

### Tests (105 total, 19 in `test_graph.py`; all pass on SQLite and PostgreSQL)
graph completeness (every line source/input and every value→page→document is an edge) · analysis
edges · masking in nodes · Prove It reaching the duplicate pages · footprint completeness under
truncation · grouping and expand · document → final tax trace · impact rings, headlines and version
scope · API normalization (bare keys, unknown refs/versions) · verification overlay for staff only ·
human links (validation, duplicates, roles, retirement, audit).

### Limitations
- The layout is a simple layered one. Columns are capped and large results open shallow, so big traces
  are explored by expanding nodes rather than shown all at once.
- Impact radius counts lines; it does not estimate tax (Iteration 6 applies `tax_effect_rates` to adjustments).

### Review follow-ups (after the Iteration 3 review)
- **Impact radius keeps the selected return version (bug fix).**
  - *Before:* opening impact for a `line:v1:…` line silently read v3 and reported 0 affected lines.
  - *API:* a `line:vN:` reference now carries its own version for impact, trace, prove and node
    lookups, and every response says which version it used. An explicit version that contradicts the
    line is refused (422), not ignored.
  - *Frontend:* every graph request sends the version. Drawer links encode it (`&v=v1`). For roots
    that aren't lines (documents, pages, values), a v1/v2/v3 picker chooses the return to read them in.
  - *Regression tests:* v1/v2/v3 lines for impact, trace and prove; a conflicting version is
    refused; values are read in the requested version; lines that exist only in v3.
- **Legible large traces.** Each column is capped at 14 nodes (`max_per_level`); the overflow joins
  its parent's "N more" group, and expanding a node always opens it fully. Fit-to-view never zooms
  below 60%, and the mouse wheel pans the canvas (pinch or +/− zooms) instead of shrinking cards.
  This also fixes the earlier "wheel zooms instead of scrolls" limitation.
- **Links refresh the graph.** Saving a link now redraws every graph view and its footprint.
- **Browser walkthrough completed:**
  - Return v1 drawer → Impact radius → "94 lines in v1", showing v1 results (total tax 77,200).
  - Prove It on SchC.9, then node inspector.
  - Form 8949 box A: legible columns, "+ 4 more" expanded, wheel pans the canvas.
  - Value impact switched v3 → v1 with the picker.
  - Link created from D23 to msg-03 in the inspector.
  - Client role: the reviewer's link is hidden, and there is no link form.

## Iteration 4: Modern CPA Workpaper ✅

**Goal:** the main working experience, organised by tax areas rather than spreadsheet tabs, with
every record a CPA expects. Large data is summarised first and expanded on demand.

### Delivered
- **Return workspace** (`/return`), with tabs:
  - **Areas** (the default)
  - **Return summary**
  - **Prior year**
  - **Records**
  - **All lines** (the previous line browser, unchanged)

  The version selector (v1/v2/v3) applies to every tab. Any line number anywhere opens the line drawer
  in place, so you never leave the schedule you are working in.
- **Area summaries** (`services/area_summary.py`): eleven areas, each showing:
  - key figures vs 2024, with the firm's variance flag
  - **traceability** (lines whose input chain reaches cited evidence)
  - **evidence coverage** (source values verified by a person)
  - open items: notes and blocking notes, evidence conflicts and reviews, engine diagnostics, prior-year swings
  - preparer and reviewer names and sign-off status (live from Iteration 7)
  - budget hours

  Each area page (`/return/area/[key]`) adds its schedules, its line list (individual sales are kept in
  the brokerage schedule), its engine diagnostics and area notes.
- **Records** (`services/schedules.py`, `/return/records/[name]`). Every row carries the refs it came
  from, and wherever TaxProof can recompute something it shows a **TaxProof recalculation** panel,
  visually separate from the engine:

  | Record | What TaxProof adds |
  |---|---|
  | Return summary & tax computation | Form 1040 and 540NR top to bottom vs 2024. California lines are matched to the 2024 *resident* Form 540 by meaning, not line number (540 line 32 ≠ 540NR line 32) |
  | Prior-year comparison | 95 comparable lines, swings flagged, plus lines that disappeared and lines new this year by area |
  | Books to tax | Client P&L (D14) walked to Schedule C, derived from what each Schedule C line cites plus the engine's notes. **89,834 → 81,854, reconciled to the dollar**; books totals re-added |
  | Depreciation by asset | Method/life, federal vs California vs AMT, disposals and §1250 recapture. Prior accumulated depreciation ties to the prior preparer's schedule; activity totals tie to Form 4562 lines |
  | Brokerage & digital assets | **295 lots → 11 source/box rows.** Lots load 25 at a time, largest gains first, filterable; a "needs attention" view (missing basis, evidence flags); box totals re-added |
  | Rentals & passive losses | Per property: rents, expenses vs 2024, net, allowed after Form 8582, assets, the condo sale on 4797, suspended losses in and out; net recomputed |
  | K-1s & basis by year | Every K-1 item and the lines it feeds. **Independent S-corp basis roll-forward** 2022→2025 (21,300 → 15,400 → 2,300 → 0, excess 21,215); notes the partnership's outside-basis gap |
  | California / Texas allocation | **Residency timeline** (CA 195 days → TX 170 days) with the move, the condo sale and state/federal payments placed in each state. Schedule CA columns A–E with California share; A − B + C = D checked per line; deduction percentage recomputed (0.6347) |
  | Carryovers | Into 2025 → lines that used them → out to 2026, federal and California |

### Found by the records (deterministic, nothing hard-coded)
- **v2 started 2025 with the wrong S-corp basis.** The independent roll-forward gives 2,300; v2's Form
  7203 started at 8,200 because it assumed no 2023 activity. v3 fixed this once the 2023 K-1 arrived.
  The K-1 record shows the disagreement when you switch to v2.
- **The +12,400 receipts item** (unmatched 1099-K added to books revenue) and **the D23 mileage**
  surface as explicit bridge rows. Iteration 5 turns them into findings with tax effect.
- **Brokerage lots needing attention:** the crypto lot with no basis (C6), and the Corvane RSU lots
  whose basis was printed "(not reported)" but recorded as 0.
- **Wages 100% California** despite the July move. Halvorsen's W-2 note says payroll kept California
  as the work state through September. The state view makes this visible; it's queued as an
  Iteration 5 state-allocation check.

### Tests (121 total, 16 new in `test_schedules.py`; all pass on SQLite and PostgreSQL)
bridge reconciliation and derivation · depreciation continuity and totals · brokerage grouping, paging,
attention filter and unique count · rentals · basis roll-forward (v3 agrees, **v2 disagrees**) · state
checks, ratio precision and residency · carryovers · tax computation order and prior-form mapping ·
area key lines, traceability, area API (verification and blocking-note counts; client view) · schedule
API and version handling.

### Limitations
- Area sign-off statuses are displayed but only change once Iteration 7 adds sign-offs.
- The residency timeline uses dated evidence in the packet; the home purchase date appears only in the
  organizer's address note (the closing statement has no extracted date).

### Review follow-ups (after the Iteration 4 review)
| # | Bug | Fix | Regression test |
|---|---|---|---|
| P1 | A blocking review note on evidence (e.g. `ev-0315`) wasn't counted in its area: Business showed 0 blocking notes | A note's areas are now **derived from what it points at** (`areas_for_ref`): an area ref, a line's area, or every area whose lines cite the value, page, document or client item, plus any stored area. This applies to both the area summaries and the Overview's area tiles. Area pages list "open notes on this area's lines and evidence" | `test_areas_for_ref`, `test_evidence_notes_count_in_area_summaries` (ev / page / document notes; resolution removes them) |
| P2 | Brokerage lots kept the previous group's page and search | The lots table is keyed by the selected group, so a new selection starts on page 1 with an empty search | `brokerage.test.tsx`: page 3 of a 60-lot group → 3-lot group requests offset 0, no search, and renders its rows; search doesn't carry over |
| P2 | Evidence links in schedules dropped the version | `EvRef` builds links with `evidenceTraceHref(id, version)` from the schedule's version | `format.test.ts` and `brokerage.test.tsx` (an `EvRef` rendered in a v2 schedule links with `&v=v2`) |
| P2 | Ratios rounded to whole numbers (0.6347 → 1) | `money()` keeps up to 4 decimals for fractions below 1, which fixes the summary, line drawer, graph nodes and checks in one place; the state view's special case was removed | `format.test.ts` (0.6347, 0.0766; dollars unchanged) |

- **Frontend tests added**: Vitest, jsdom and Testing Library (`npm test` in `frontend/`), 8 tests.
  Each one was confirmed to **fail with its fix reverted** and pass with it.
- **Browser walkthrough**:
  - Business shows 1 blocking note from the `ev-0315` note.
  - Brokerage: page 3 of Brightpath box D (150 lots) → Meridian box D shows all 9 lots with an empty search.
  - Evidence links in the v1 books-to-tax schedule open "Downstream reach (v1)".
  - The summary shows 0.6347 and 0.0766.
- Tests: **123 backend** (SQLite and PostgreSQL) and **8 frontend**.

## Iteration 5: Challenge Return assurance engine ✅

**Goal:** an independent assurance engine that does not trust the supplied engine. It uses
deterministic Python rules, keeps its output apart from the engine's diagnostics, and estimates tax
effects without pretending to rerun the engine.

### Delivered
- **Assurance engine** (`services/assurance.py`): 20 reusable rules in 17 families, run per return
  version and cached by packet hash (about 0.35s). **No rule names a document id.** Each one looks
  for a pattern:

  | Family | Rule (generic pattern) |
  |---|---|
  | Duplicate page | Two pages that are the same sheet *and* both feed the same line |
  | Duplicate economic transaction | A 1099-K amount added on top of books when the books' own detail names that processor and amount; the same interest reported for the same account on two documents |
  | Duplicate document | A document copy whose values feed the same line as the original |
  | Source totals | Page items vs printed page totals; 1099-K months vs box 1a; books totals |
  | Brokerage summary-to-detail | Printed 1099-B summary vs extracted lots; **traces the gap to an unread page** |
  | Cross-document | Distinct W-2s vs wages, federal and California withholding |
  | Prior-year continuity | Capital loss carryover recomputed from 2024 Schedule D; passive losses; accumulated depreciation; IRA basis |
  | Books to tax | The Iteration 4 bridge must land on Schedule C line 31 |
  | Basis | Stock-plan supplement basis matched to broker lots (same date, company and broker); S-corp roll-forward; lots with no basis |
  | State allocation | California-source wages vs the move date (employment dates and a move-date paystub); resident days; ratio |
  | Questionnaire | Table-driven answer-vs-file contradictions (sales, crypto, IRA basis, employer coverage) |
  | Payments | Federal estimates vs the IRS transcript; California estimates vs the FTB account and the payment's designated year |
  | Carryovers | SEP carryforward, minimum tax credit, capital losses out |
  | Completeness | 2024 payers and K-1 entities present in 2025; prior preparer's open items closed by evidence |
  | Extraction integrity | Readings that disagree with the page or organizer and reach the return (e.g. dependent SSN) |
  | Currency conversion | Foreign income converted at another period's rate |
  | Judgment | Whole-system replacements deducted as repairs: surfaced, never decided |

  - *Evidence as of the version:* a document or message received after a version was computed isn't
    held against that version. For example, the move-date paystub arrived after v2.
  - *Tax effects:* each finding maps its line to a `tax_effect_rates` category with a sign. Items
    fully sourced to California use `ca_source_income`. Payments change the balance one-for-one.
    Effects are labelled estimates, judgment items are shown as "potential", and anything over
    $1,000 is flagged for partner review (firm rule).
  - *Engine diagnostics* are linked to related findings but never merged with them.
- **Run history**: a `challenge_runs` table (migration `0004`) records who ran it, when, and on which
  version. The next run reports what's new, changed or resolved, and every run is audited.
- **API**: `GET /api/challenge`, `GET /api/challenge/finding?id=`, `POST /api/challenge/runs`,
  `GET /api/challenge/runs`. Staff only; clients get 403.
- **UI** (`/challenge`, a new **Challenge** nav item, which is a signature feature):
  - The supplied engine's "computed" alongside TaxProof's failed / needs-judgment / passed counts.
  - The summed estimated effect, labelled as an estimate.
  - Coverage by family, and findings filterable by status.
  - Each finding detail shows:
    - the engine result next to the independent result
    - a breakdown (the duplicate page highlighted)
    - the tax-effect arithmetic
    - affected lines with headline reach and Prove It / Impact / Where it goes
    - resolved evidence with links to pages
  - The engine's own diagnostics sit in a separate violet section.
  - The Overview shows a live Challenge strip.
  - AI explanation is marked as planned for Iteration 9; nothing generates prose.

### Results on v3 (61 checks: 14 failed, 8 need judgment, 39 passed)
| Finding | Engine | TaxProof | Est. effect (fed / CA) |
|---|---|---|---|
| **Mileage: D23 page 3 duplicates page 2** (required demo) | 11,800 mi | 8,100 mi | +919 / +80 |
| **Paywell 1099-K already in books** (required demo) — corroborated: 1099-NEC 142,000 + non-1099 9,300 = books 151,300 | 163,700 | 151,300 | −4,402 / −384 |
| RSU lots taxed at 0 basis; plan statement D11 gives 19,100 / 19,100 / 9,420 | gain at 0 basis | gain at adjusted basis | −6,647 ×2, −2,242 / CA-sourced |
| California wages include post-move pay (W-2 box 16 vs move-date paystub D73) | 218,400 | 129,569 | 0 / −5,685 |
| Federal Q4 estimate: client memory 4,000 vs IRS transcript 3,000 | 13,000 | 12,000 | balance +1,000 |
| California estimate of 2025-09-15 designated to 2024 (FTB holds as 2024 credit) | 14,000 | 10,500 | CA balance +3,500 |
| Northlake interest counted twice (same account ending 7731) | 3,680 | 1,840 | −640 / −127 |
| Meridian 1099-B: unread page 32 holds a sale worth exactly the 250 gap | 71,715 | 71,965 | −21 / −2 |
| Swedish interest converted at the 2024 average rate | 1,747 | 1,871 | +43 / +9 |
| Theo's SSN in the organizer differs from his 2024 return (critical — e-file risk) | — | — | — |
| D62 provider TIN transposed; D64 handwritten "$?,500" | — | — | — |

Needs judgment: self-employed health insurance while eligible for employer coverage (potential +4,464 /
+605), HVAC replacement deducted as a repair, the crypto lot with no basis, questionnaire answers the
file contradicts, the unresolved 2023 Form 3520 item, and an extension payment not yet visible on the
transcript snapshot. On v2 the engine also fails the S-corp basis and the missing Ridgeline K-1, both
of which v3 fixed.

### Tests
- **Backend:** 137 tests, 16 in `test_assurance.py`, passing on SQLite and PostgreSQL. They cover both
  required demo cases end to end, every other finding, the no-false-positive check (a Harborview lot
  with the same acquisition date), required family coverage, version behaviour, packet immutability,
  and the API (permissions, linked engine diagnostics, run history and changes).
- **Frontend:** 12 tests. `finding-card.test.tsx` covers the TaxProof vs engine labelling, units,
  estimate and potential wording, engine-also-flagged, and partner review.

### Limitations
- Estimated effects are linear at v3's rates and are not additive in reality; the UI says so.
- Findings can't yet be accepted or dismissed: Iteration 6 adds adjustments and Iteration 7 adds the
  Uncertainty Inbox and judgments.

### Review follow-ups (after the Iteration 5 review)
| # | Issue | Fix | Regression test (sweeps every finding, every version) |
|---|---|---|---|
| P1 | Finding evidence returned a full SSN, even to staff without clearance | `mask_resolved()` masks every resolved reference before it leaves the API, and the Challenge API also masks every string in finding payloads (titles, summaries, breakdowns). Unmasked values are only available through the logged reveal endpoint, whatever the caller's clearance | `test_no_challenge_response_leaks_sensitive_values` × 3 users: scans the overview and every finding detail in v1–v3 for any raw SSN, IP PIN, bank number or sensitive extracted value |
| P2 | v1/v2 used evidence received later (D26 for the SEP check) | The cutoff is enforced where rules *get* evidence: `docs_of_type()` and `available()` drop documents received after the version was computed, and `agency_as_of()` drops later agency snapshots. The transcript fallback that used a later snapshot was removed; with no record yet, payment checks say "not yet confirmable" | `test_no_finding_uses_evidence_from_after_its_version` (documents and agency snapshots), `test_sep_check_waits_for_the_contribution_confirmation` |
| P2 | Run history missed amount changes | Runs compare status, severity, difference, and federal and California effects; amounts count when they move by more than $0.50. The response includes `changed_detail` (old → new per field), shown on the page | `test_run_history_detects_amount_changes` (+500 detected, +0.40 rounding ignored) |
| P2 | Some evidence references didn't resolve (`household`) | The resolver supports organizer sections (`household:residency`, `household:addresses`), and the rules cite them | `test_every_evidence_reference_resolves` |
| — | The headline effect mixed tax estimates with payment corrections | Shown as two separately labelled figures: **estimated change in tax** (−19,637 federal / −8,873 California, 9 findings) and **change in balance due from payment corrections** (+1,000 / +3,500, 2 findings; tax unchanged). The Overview strip is labelled the same way | `test_effects_are_split_into_tax_and_balance` |

- Each new test was confirmed to **fail with its fix reverted** and pass with it.
- **Browser check:** as Marcus (no clearance), Theo's identity finding shows `•••-••-3390` and no full SSN
  anywhere on the page; the two effect figures appear separately.
- Tests: **149 backend** (SQLite and PostgreSQL) and **12 frontend**.

### Review follow-ups (after the Iterations 1–5 review)
| # | Issue | Fix | Regression test |
|---|---|---|---|
| P2 | S-corp basis for v1/v2 used the 2023 K-1 (D40, received June 5) to produce a definitive 2,300 for March returns | The evidence cutoff now lives in the **shared schedules** too (`available_docs()`): K-1 basis, books-to-tax and residency only use documents received by the version's cutoff. A basis year without a K-1 becomes an explicit **evidence gap**: no comparison is made, and the engine's assumption (8,200) is reported. The Challenge rule raises "S corporation basis cannot be proven" as needs-judgment; the K-1 record shows a gap banner and tags K-1s "received after v2". v3, which has D40, still rolls forward and agrees | `test_schedules_never_use_evidence_received_after_their_version` (every document a schedule cites, v1–v3), `test_basis_roll_forward_reports_a_gap_without_the_2023_k1` |
| P2 | Prove It / trace / impact on a verification node returned 404 | Roots are validated against the **same view the caller sees** (packet graph + their workpaper overlay); a resolvable packet ref with no graph node is added to the view. Clients, who have no overlay, still get 404 | `test_workpaper_overlay_nodes_are_valid_roots` |
| P2 | Area open/blocking counts went stale after creating or resolving a note | `useRefreshAfter()` revalidates every cached view a write affects: notes → note threads, area summaries, Overview tiles; verifications → area coverage, documents, values, graph. It uses the **bound SWR cache**; the first version used SWR's global `mutate` and the new test caught that it would miss views under their own cache provider | `notes-refresh.test.tsx`: a live area counter follows a new review note (0 → 1 blocking) and its resolution (→ 0) without a reload |
| P2 | California prior year differed between the summary (12,520) and the line drawer (none) | One rule everywhere: `prior_value()` (the Form 540 → 540NR map by meaning) is used by the drawer and by the graph's 2024-counterpart edges. The drawer now names the 2024 line it compared against | `test_prior_year_counterpart_is_the_same_on_every_screen` (every v3 line: drawer = rule = summary = graph edge) |

- Each new test was confirmed to **fail with its fix reverted** and pass with it.
- **Browser walkthrough**:
  - The v2 K-1 record shows the 2023 gap banner and K-1s tagged "received after v2".
  - Prove it from a verification node's inspector opens its graph.
  - The Business area's open (blocking) count goes 0 (0) → 1 (1) on saving a review note, with no reload.
  - The F540NR.64 drawer shows 12,520 from CA540.64.
- Tests: **154 backend** (SQLite and PostgreSQL) and **13 frontend**.
- The Iteration 4 statement that "v2 started the S-corp basis wrong (8,200 vs 2,300)" is superseded. With
  the evidence v2 actually had, basis was **unprovable**: the 2023 K-1 hadn't arrived and the engine
  assumed no 2023 activity. That is the honest finding for v2.

## Iteration 6: Adjustments, versioning, undo, What-If ✅

**Goal:** let CPAs change the *workpaper* without ever overwriting the engine output, show what each
change is worth (as a labelled estimate), and explain how the return moved between versions and what
the engine's own alternatives would do.

### Delivered
- **Adjustment objects** (`adjustments` table, migration `0005`). Each one keeps the target line, original
  value, adjusted value, difference, unit (dollars or miles), reason, evidence refs, the finding it came
  from, status, review requirement, estimated federal and California effect, creator, approver and a full
  history. The packet and the engine's line values are never touched.
- **Lifecycle:** proposed → applied → undone → restored (applied again). There is **one active
  adjustment per line**. Undo and restore append to the history rather than deleting anything. Restoring
  clears an earlier approval, because the change has to be approved again.
- **Approval rules (server-side):** an estimated effect over $1,000 (federal or California) needs a
  **partner**; anything smaller needs a reviewer. Nobody approves their own adjustment. Only the creator
  or a reviewer/partner can change an adjustment's state. Clients can't see adjustments.
- **Estimated effect** comes from the version's `tax_effect_rates` (the same `line_category` mapping the
  Challenge engine uses). Non-dollar lines go through the engine's own ratio to the line they feed
  (business miles → mileage deduction). Payment lines change the balance due only. Every figure is
  labelled "estimate". **Engine vs workpaper estimate** shows the supplied totals next to totals plus
  applied effects, and says plainly that this is not an engine recomputation.
- **From a Challenge finding:** "Create & apply adjustment" (or "Propose") uses the finding's proposed
  value. A finding whose engine value is not the target line's own value (for example the broker-summary
  total vs one lot) is refused with 422, so a summary figure can never overwrite a detail line.
- **Bulk apply / undo / restore / approve** is all-or-nothing in one transaction. Any failure rolls back
  everything and returns each item's reason. Duplicate ids are refused.
- **Line drawer: "Workpaper value"** shows the engine value next to the effective value, with an adjust
  form for current-version numeric lines. The evidence graph gains Adjustment nodes (`ADJUSTED_BY`).
- **Every action is audited** in the hash chain (`adjustment.created/apply/undo/restore/approve/bulk`).
- **Tax Time Machine** (`services/time_machine.py`, `GET /api/return/time-machine?from=&to=`): compares
  any two versions, in either direction.
  - Summary deltas and the tax change.
  - Every changed line, grouped by area.
  - Documents now used, no longer used or superseded; diagnostics added, removed or changed.
  - **Why:** the trigger, the season events and the documents received between the runs.
  - **Driver lines:** changed lines whose own inputs did not change, meaning new evidence entered there,
    each with the new source documents.
  - Consecutive versions are cross-checked against the packet's `changes_from_previous`. v1→v2 and
    v2→v3 agree exactly (v2→v3: all 89 changes).
- **What-If Lab** (`GET /api/return/what-if`) displays only the engine alternatives supplied in the
  packet, plus the April extension estimate. For each alternative it shows the choices, federal and
  California total tax against the base, the changed lines, and any open Challenge finding on a line
  it changes (HVAC → the repair-vs-improvement finding). Nothing is computed.

### Example: mileage (the required case)
D23 page 3 is a second scan of page 2, so SchC.44a = 11,800 counts 3,700 miles twice. From the finding:
original **11,800 miles → adjusted 8,100 miles** (Δ −3,700). The estimated effect is **federal +919,
California +80**, reached through the engine's mileage ratio and v3's rates. That needs reviewer
approval. The engine still says 11,800; the workpaper says 8,100; the graph shows the adjustment.

### Found and fixed while building (each has a regression test)
- **Audit chain broke on PostgreSQL only:** a −0.0 effect was hashed as `-0.0`, but JSONB stores it as
  `0`, so verification failed. `audit._storable()` now normalises payloads before hashing, and effects
  never produce −0.0.
- **The broker-summary finding would have replaced one lot's gain with the whole 1099-B total.** It no
  longer offers an engine target, and from-finding refuses any proposal whose engine value is not the
  target line's own value.
- **The same-account interest finding pointed at a computed total (SchB.2).** It now carries an explicit
  adjustment of the duplicated input line.

### Tests
- **Backend:** 170 tests, 16 in `test_adjustments.py`, passing on SQLite and PostgreSQL. They cover:
  - effect estimation (mileage ratio; payment lines being balance-only) and target validation
  - the mileage case end to end: values, effect, effective value, packet unchanged, undo/restore
    history, graph edge
  - every proposable finding becoming a valid adjustment
  - one active adjustment per line
  - bulk all-or-nothing
  - approval independence and the partner threshold
  - role enforcement
  - Time Machine agreeing with the engine for every consecutive pair, plus v2→v3 drivers, any pair and
    the reverse direction
  - What-If returning only supplied values
  - an audit chain with negative zero
- **Frontend:** 16 tests (3 new in `adjustments.test.tsx`): estimate labelling, a bulk failure keeping
  the selection and showing every reason, and how differences in miles are formatted.
- **Browser walkthrough (as Priya):**
  - Create & apply from the mileage finding, then "open in Adjustments".
  - The estimate table shows 1 applied (+919 / +80).
  - Undo returns it to 0 applied; restore brings it back.
  - The SchC.44a drawer shows engine 11,800 / workpaper 8,100.
  - Time Machine v2→v3 shows 6 drivers (D40 basis, D37 K-1 lines, the 36,000 extension payment) and
    agrees with the engine.
  - What-If shows 5 alternatives and the extension estimate.

### Limitations
- Effects are linear estimates at one version's rates. Several adjustments are summed, which real tax
  does not do (brackets, phase-outs, AMT). The UI says so. The engine is never rerun.
- Adjustments target the current version only; older versions are read-only history.
- Only one adjustment per flow path can be active. To correct the mileage, adjust the miles *or* the
  car expense, not both.
- What-If can only show alternatives the packet supplies; there is no free-form scenario input.
- Adjustments don't yet feed area sign-offs (Iteration 7) or the filing package and lifecycle
  (Iteration 8).

### Review follow-ups (after the Iteration 6 review)
| # | Issue | Fix | Regression test |
|---|---|---|---|
| P1 | Bulk actions weren't atomic on SQLite: in [valid, nonexistent], the valid item stayed applied after the 409 | Two layers, each enough on its own. (1) Bulk no longer uses savepoints. `_transition` raises before changing anything, so one transaction plus a rollback undoes every item. (2) The SQLite engine uses SQLAlchemy's documented pysqlite recipe (the driver's own transactions are off and SQLAlchemy emits `BEGIN`). Before this, a SAVEPOINT opened outside a transaction was *committed* by its RELEASE | `test_bulk_rolls_back_items_that_succeeded_before_a_failure`: valid-then-invalid, two valid then invalid, invalid first. All items stay proposed, no audit event survives, and the chain verifies |
| P2 | An adjustment from the RSU finding (F8949.B.N1) re-estimated California at −649 instead of the finding's −1,222, dropping `ca_source_income` | The rate context is one function, `ca_category_for()` (a Form 8949 lot sold while a California resident is California-source income). The Challenge rule and `estimate_effect` both use it, so adjustments typed by hand get it too | `test_an_adjustment_keeps_its_findings_rate_context`: every proposable finding's adjustment has exactly the finding's federal and California effect and category, and the manual F8949.B.N1 estimate is −1,222 |
| P2 | Mileage 11,800 → 8,100 and its car expense 8,260 → 5,670 could both be active, counting +919 / +80 twice | `flow_related()`: a line's upstream inputs and downstream consumers, transitively. Create, apply and restore (single or bulk) refuse a line in the same flow path as another active adjustment, naming it and how they're linked. Lines that only meet in a later total (gross receipts and an expense) stay independent, and all 10 Challenge proposals can still be active together | `test_related_lines_cannot_both_carry_an_adjustment`: both directions, restore, from-finding and bulk restore are refused; the summary counts +919 once; an unrelated line is still allowed |

- Each new test was confirmed to **fail before its fix** (the bulk test also fails with the original
  savepoint code and no engine fix, and passes with either layer alone).
- **Browser check (as Priya):**
  - The RSU finding's "Create & apply" gives an adjustment of federal −6,647 / California −1,222
    (`ca_source_income`).
  - With mileage applied, the SchC.9 drawer refuses 5,670 with "SchC.9 is computed from SchC.44a,
    and SchC.44a already has active adjustment #2 … would count one correction twice".
  - The estimate is 81,962 − 6,647 + 919 = 76,234 federal and 18,874 − 1,222 + 80 = 17,732 California.
- Tests: **173 backend** (SQLite and PostgreSQL) and **16 frontend**.

## Iteration 7: Judgment + collaboration ✅

**Goal:** capture everything humans contribute: what is still uncertain, what was decided and why, who
signed what, and what the client said. Keep sign-offs honest when the work underneath them changes.

### Delivered
- **Uncertainty Inbox** (`services/inbox.py`, Review → Uncertainty Inbox).
  - **Sources.** Items are derived, never copied, from:
    - open review notes
    - TaxProof findings that failed or need judgment
    - engine warning diagnostics that no finding already covers
    - adjustments and judgments awaiting approval
    - client questions
  - **Groups.** Each open item sits in exactly one group: **Filing blockers**, **Conflicts**, **Missing
    evidence**, **Professional judgment**, **Client questions**, **Review notes**.
    - The group comes from the item's nature (family and status, or diagnostic code words), never its id.
    - Blockers come from firm rules: blocking review notes, escalations, adjustments over 1,000 awaiting
      the partner, and client questions marked "needed before filing".
  - **Actions** (server-enforced):
    - **Resolve.** Review notes are resolved by a reviewer.
    - **Accept with explanation.** Reviewer or partner, at least 10 characters.
    - **Assign.** To staff only.
    - **Escalate.** The item becomes a filing blocker that only the partner can decide.
    - **Ask client**, **Create adjustment** (findings with a single-line fix), **Record judgment**.
  - **Derived handling.** An item is handled when:
    - an adjustment made from it is applied,
    - a judgment is recorded about it, or
    - an accepted client answer resolves it.

    Undoing the adjustment reopens the item.
  - `issues` holds only what people decided: assignment, escalation, resolution and history.
- **Client questions** (`client_questions`).
  - Staff ask from an inbox item (or about any line or document). The question goes to one client or the
    household, optionally marked "needed before filing".
  - The client sees only client-facing fields on Review and answers there.
  - The firm then **accepts the answer as evidence**:
    - it becomes a `client_answer:N` node on the graph, and the line it is about is CONFIRMED_BY it;
    - it can resolve the item it came from;
    - it reopens the sign-offs it affects.
  - Withdrawal is recorded. Text is masked like every other free text.
- **Judgment Ledger** (`judgments`, `services/judgments.py`).
  - **Fields:** topic, the lines it is about, decision, alternatives considered (at least one, each with
    why not), rationale, **authority** (required by firm rule), evidence, **tax effect**, preparer, reviewer,
    partner and timestamps.
  - **Effects are never invented.** A decision is one of:
    - *keep the return as computed* (0);
    - one of the packet's **engine alternative runs** (`what_if`; exact engine figures, labelled "engine
      run"; alternatives touching the item's lines are marked related);
    - *another treatment* (effect "not computed").
  - **Tax at stake** is the largest difference between the decision and any alternative. Over 1,000 it
    needs partner approval, mirroring the adjustment rule.
  - **Lifecycle:** recorded → approved (reviewer), or recorded → reviewed → approved (partner). Nobody
    reviews their own judgment. A revision supersedes; nothing is edited.
  - A `judgment:N` graph node is RELATED_TO its lines.
- **Living sign-offs** (`signoffs`, `services/signoffs.py`; Review → Sign-offs, and on every area page).
  - Prepared → reviewed → partner, per area.
  - **Rules:**
    - in order;
    - nobody reviews an area they prepared, nor one containing an applied adjustment or a judgment they made;
    - open blocking review notes on the area stop the reviewed and partner sign-offs;
    - partner-level adjustments and judgments must be approved before the partner signs.
  - Other open items don't stop a sign-off; they are recorded on it ("4 open at signing").
  - **Reopening.** These changes reopen the area's reviewed and partner sign-offs:
    - an adjustment applied, undone or restored on one of the area's lines;
    - a judgment recorded or revised;
    - a client answer accepted;
    - a verification withdrawn;
    - an evidence link created or retired.

    Reopening covers the area of the change **and every area computed from it** (see the review follow-ups).
    Each reopen records **exactly why**: what, by whom, when. Example: "Adjustment #1 applied on SchC.44a
    (11,800 miles → 8,100 miles) by Priya Raman." The prepared sign-off stays; the preparer owns the work
    in progress.
  - The API response that caused a reopen lists it, so the Challenge drawer and the Adjustments tab say
    "Sign-offs reopened: business reviewed, business partner" at once.
- **Filing gate** (`GET /api/filing/readiness`, Filing page). Deterministic checks, each naming its items:
  - no open blocking review notes
  - no escalations
  - required approvals done
  - blocking client questions answered and accepted
  - every other item dispositioned
  - every area prepared, reviewed and partner-signed

  **Open blocking review notes disable filing.** The File button stays disabled and lists the reasons.
  `assert_can_file()` is the gate Iteration 8's lifecycle will call.
- **Audit.** Every action is written to the hash chain (`inbox.*`, `client_question.*`, `judgment.*`,
  `signoff.signed`, `signoff.reopened`).
- **Fixed in passing (Iteration 5 bug):** the identity finding cut the document title at 40 characters
  ("…prepared by Del"). It now shows the document id and full title.

### The demo path (browser, as the four people)
1. **Sign Business.** Priya signs prepared ("4 open at signing"), Daniel reviewed, Helen partner: all three ✓.
2. **Apply the mileage adjustment.** Priya uses Create & apply on the mileage finding. The drawer says
   "Sign-offs reopened: business reviewed, business partner". The board shows Reviewed **REOPENED** and
   Partner **REOPENED**, each with *Why: Adjustment #1 applied on SchC.44a (11,800 miles → 8,100 miles) by
   Priya Raman*. Prepared stays ✓.
3. **Ask the client.** From the inbox, Priya asks the household about the self-employed health
   insurance contradiction (qa-25). The question appears under Filing blockers.
4. **The client answers.** Ngozi sees only the question on Review and answers.
5. **Accept the answer.** Priya accepts it as evidence. The inbox item is resolved by the client
   answer, and Prove It on Sch1.17 shows the ClientAnswer node.
6. **Record a judgment.** Priya records the HVAC judgment: capitalize, with the engine's own
   `hvac_improvement` run giving +3,633 / +896. At stake 3,633, so partner approval is required. Daniel
   reviews it and Helen approves it.
7. **Filing.** The page reads "filing disabled · 3 checks failing", naming the reviewer approval, the
   open items and the unsigned or reopened areas.

### Tests
- **Backend:** 185 tests, 12 new in `test_collaboration.py`, passing on SQLite and PostgreSQL and in a
  different file order. They cover:
  - grouping: one group per item, by nature; covered and informational diagnostics excluded; actions
    follow the role; clients and the firm administrator are refused
  - no full SSN in the inbox for uncleared staff
  - accept, resolve, escalate and assign, with their permissions and audit events
  - a blocking review note disables filing and the review sign-off until a reviewer clears it
  - sign-off order, roles and independence
  - **the mileage adjustment reopening Business reviewed and partner with the exact reason** (an
    unrelated payments change does not; undo reopens again; a reviewer who changed the area cannot review it)
  - partner sign-off waiting for partner approvals
  - client question → answer → accepted evidence on the graph (client-only fields; the wrong client
    and staff cannot answer)
  - judgment options from the packet, validation, review chain, supersession and the graph node
  - **the gate opens only when everything is decided and signed**, and one new blocking review note
    closes it again
- **Frontend:** 21 tests (5 new in `collab.test.tsx`):
  - blockers first with the reason, and acceptance posting its explanation
  - REOPENED with the exact reason
  - why a user cannot sign
  - filing disabled with named blockers
  - the client view without internal refs, sending the answer

### Limitations
- **Version changes.** The packet is fixed at v3, so "the return was recomputed" can't reopen anything
  yet. Sign-offs record their version for when it can (Iteration 8 replay).
- **Client question drafts** are a deterministic template. AI drafting is Iteration 9.
- **No time-boxed notifications.** Assignment shows in "assigned to me" only.

### Review follow-ups (after the Iteration 7 review)
| # | Issue | Fix | Regression test |
|---|---|---|---|
| P1 | Judgment authority and alternative text, and graph metadata, returned a full SSN to an uncleared user | `mask_payload()` masks every string in a payload, however nested. Every response that carries text people typed uses it: judgments, inbox items (history, escalation and resolution notes), client questions, sign-off reasons, readiness, adjustments, notes, verifications, evidence links and audit-event payloads. **Every overlay node's label and metadata and every overlay edge in the graph** is masked in one place, so a new field or record type can't bypass masking | `test_no_free_text_anywhere_leaks_an_ssn`: a synthetic SSN typed into every free-text field of every record type, then 15 views (incl. graph node, prove and trace) read as the uncleared preparer, the preparer and the partner, plus the client's view and the audit log |
| P1 | An escalation could be cleared without the partner: a preparer applied an adjustment to the escalated finding; a reviewer resolved the escalated note through the notes endpoint | `guard_escalation()` runs on **every path that can handle an item**: inbox actions; creating, applying or restoring an adjustment for the finding; approving or undoing an escalated approval (including in bulk); recording a judgment about it; reviewing an escalated judgment; accepting or withdrawing an escalated client question, or an answer that would resolve the item; and the original notes endpoint. Only the partner passes | `test_escalation_cannot_be_bypassed_through_another_endpoint`: each of those paths is refused (bulk returns the reason); the item stays a filing blocker until the partner acts by any route |
| P1 | California's reviewed and partner sign-offs stayed signed after the mileage correction changed its figures | `affected_areas()`: the areas of the changed line or evidence (**direct**), plus every area with a line computed from it at any depth (**downstream**, with the nearest such line as `via`). The reason says so: "California is affected downstream: the change flows into SchCA540NR.12.A (Business income (Schedule C) - federal)". The card shows a "downstream via …" chip. A payment correction flows only into payment totals and leaves California signed | `test_downstream_areas_reopen_when_a_calculation_they_rest_on_changes` (direct and downstream scopes, and the payment case) |
| P2 | Revising a judgment to new targets left the original area signed | A revision reopens the areas of **old ∪ new** targets | `test_revising_a_judgment_reopens_the_areas_it_used_to_support` |
| P2 | An accepted client answer (`client_answer:N`) could not be cited as evidence | `evidence_kind()` resolves packet references **and** accepted workpaper evidence. Verifications ("Confirmed with client" accepts the `client_answer` kind), adjustments, judgments and evidence links can cite an accepted answer. An unaccepted one is refused with the reason. Graph edges to overlay nodes are kept | `test_an_accepted_client_answer_can_be_cited_as_evidence` (refused until accepted; then verification, adjustment, judgment and link all cite it and all appear on its graph node) |

- Each new test was confirmed to **fail before its fix**.
- **Browser check:**
  - The mileage finding is escalated. As Priya, "Create & apply" is refused with "…was escalated to the
    partner…".
  - As Helen it succeeds and the drawer reads "Sign-offs reopened: business reviewed, business partner,
    california reviewed, california partner".
  - The California area page shows both REOPENED with "downstream via SchCA540NR.12.A" and the reason.
- Tests: **190 backend** (SQLite and PostgreSQL; collaboration module also alone and in another order)
  and **22 frontend**.

## Iteration 8: Filing, post-filing and examination ✅

**Goal:** the workpaper survives beyond preparation. File what was approved, prove later exactly what
was filed, change it only by amendment, and defend it in an examination years later.

### Delivered
- **Filing lifecycle** (`services/filing.py`, `api/filing.py`, Filing page):
  - **States:** Preparing → Ready for Review → Partner Approved → Client Approved → Ready to File →
    Submitted → Rejected / Accepted → Filed → Frozen.
  - **Firm actions** (role-checked, every one audited):
    - *hand off* (every area prepared)
    - *partner approval* (partner; the full Iteration 7 gate, so an open blocking review note stops it)
    - *ready to file* and *submit* (reviewer or partner; gate re-checked)
    - *correct and resubmit*
    - *record as filed*
    - *freeze* (partner)
    - *reopen* (partner, with a reason; approvals must then be given again)
  - **Replay of the season.** The packet's timeline after v3 is replayed strictly in order, each event at its
    scripted time, and only when the lifecycle allows it. For example, the client approval waits for the
    partner and the payment waits for a filed return. Replayed events:
    - client messages
    - client approval and Forms 8879 / FTB 8879 (PINs masked)
    - the e-file rejection, and D71 + msg-10 arriving
    - federal and California acceptance
    - federal payment and California refund (amounts from the return as filed)
    - quality-review selection and next year's engagement
    - the 2028 Letter 566
  - **Approval of exact content.** Partner approval records a fingerprint of the return's content (version,
    applied adjustments, judgments). The client approval replay, ready-to-file and every submission refuse
    if the content has changed since: "The return changed after the partner approved it (applied
    adjustments 2 → 3 (SchC.8))".
  - **Rejection → correction → acceptance.**
    - The federal rejection (R0000-504-02, Theo's TIN; California held) is **linked to the critical identity
      finding TaxProof had raised before filing**.
    - Resubmission needs a correction note and evidence. Evidence that had not arrived at the replay clock is
      refused ("D71 had not been received yet at 2026-07-13T17:04").
    - After tl-22, D71 and msg-10 are accepted.
  - **Write locks** (`api/locks.py`). From submission, adjustments, judgments and sign-offs are refused ("The
    return is Submitted: … is locked"). Once frozen, notes, verifications, links, client questions and inbox
    actions are refused too; only amendments and examination responses remain.
- **Immutable filed snapshot.**
  - At *submit*, the package being sent is built and hashed: engine figures plus applied adjustments (labelled
    as estimates), every line's engine and filed value, documents used and superseded, sign-offs, judgments,
    verifications, accepted client answers, unresolved and accepted-with-explanation items.
  - *Record as filed* writes exactly the accepted package as the snapshot, with its hash also in the audit
    chain. Every read re-verifies the hash, so tampering shows as "content does not match its hash".
- **Filing certificate** (`/filing/certificate`, printable):
  - return version
  - effective adjustments
  - documents used and superseded
  - preparer, reviewer and partner sign-offs
  - client approval
  - all four e-file submission ids (including the rejected and not-transmitted ones)
  - acceptance dates, payment and refund
  - judgments, items accepted with explanations, and unresolved items
- **Amendment layer.** After filing, a draft amendment changes lines against the latest snapshot (effects
  estimated at the filed version's rates). It is partner-approved (independent of its preparer), then filed
  by a reviewer or partner as a **new snapshot**. The original snapshot keeps the same bytes and hash.
- **Examiner Mode** (`/examiner`, new nav item):
  - **Source.** Reconstructed from the filed snapshot plus the immutable packet graph, not from today's
    workpaper.
  - **For any line:**
    - reported (and originally filed) amount, and the engine's value
    - calculation: rule, description, inputs at their filed values
    - evidence: documents, pages and values upstream; accepted client answers
    - adjustment history
    - verifications on the line or its evidence
    - judgments
    - TaxProof's independent reconciliation
    - filed result: filing and acceptance dates, amendments, snapshot integrity
  - **Excluded:** review notes, the inbox, escalations and assignments, question threads, and reopen
    history. The view lists what it excludes.
- **2028 notice response package.**
  - The Letter 566 items are mapped to lines deterministically: "Schedule A line 12 (Form 8283)" →
    SchA.12 + the Form 8283 lines; "Schedule C gross receipts" → SchC.1.
  - For each item, *Assemble* collects the filed amounts, reconciliations and every exhibit connected to
    those lines. The explanations and cover letter can be edited in draft.
  - The partner approves it (not the preparer), which locks it with a content hash. A notice can only be
    answered once it has been received in the replay.

### Demo path (browser)
1. Priya hands off. Helen approves as partner.
2. Replay tl-18 to tl-20: Client Approved, PINs shown as •••••, "exactly what the client approved".
3. Mark ready to file, then submit. Replaying tl-21 gives **Rejected**, with "TaxProof had flagged this
   before filing: Theo Lindqvist-Okafor's SSN…".
4. Resubmitting with D71 is refused ("not received yet"). Replay tl-22, then resubmit.
5. Replay tl-23 (federal accepted) and tl-24 (California accepted). Record as filed: snapshot #1, hash
   verified.
6. Replay the payment, refund, quality review and next year. Replay **Letter 566**.
7. Examiner Mode: SchC.1 reported 151,300 (engine 163,700) with its calculation, 22 pieces of evidence, the
   adjustment history and the reconciliation 142,000 + 9,300 = 151,300.
8. Priya assembles the response (9 + 21 exhibits). Helen approves it, which locks it with a hash.

### Tests
- **Backend:** 197 tests (7 new in `test_filing.py`), passing on SQLite and PostgreSQL.
  - The filing module runs on **its own database** (a temporary SQLite file, or a `filing_test` schema on
    PostgreSQL), so freezing never affects other modules.
  - It covers, end to end:
    - the gates (blocking review note; a role-gated client approval)
    - content changed after partner approval
    - the return locked while submitted
    - the rejection linked to the identity finding
    - the evidence-received cutoff
    - two-jurisdiction acceptance
    - snapshot values and filed date; the certificate's fields
    - post-filing amounts
    - judgments refused after filing
    - **tampering detected** and restored
    - the notice not answerable before receipt; line mapping; the examined item (evidence, calculation,
      adjustment, reconciliation, nothing internal)
    - response approval and locking
    - an amendment creating a new snapshot while the original hash stays the same
    - freezing locking every collaboration write
    - the audit chain still valid
    - the client's view having no internal detail
- **Frontend:** 27 tests (5 new in `filing.test.tsx`): the rejection in the stepper with its linked
  finding, the resubmission's note and evidence, replay vs waiting, and the examined item.

### Limitations
- **Effects are estimates.** The filed totals that include adjustments are estimates (engine + rate × change),
  labelled as such on the snapshot, certificate and post-filing amounts. The engine is never rerun. Lines in
  between that are not exact combinations of their inputs (tax computations, limitations) are marked "not
  recomputed".
- **Replay clock.** Firm actions are stamped at the replay clock (the last event's time), not at a real
  submission time; agency events keep their packet timestamps.
- **Reaching partner approval.** The full Iteration 7 gate requires dispositioning every inbox item and
  signing all 11 areas at three levels. That is real work in the UI; the walkthrough prepared it through the
  API.
- **Templated text.** Notice response explanations and the cover letter are deterministic templates;
  AI-drafted wording is Iteration 9.

### Review follow-ups (after the Iteration 8 review)
| # | Issue | Fix | Regression test |
|---|---|---|---|
| P1 | The filed snapshot contradicted itself: total tax 81,962 on F1040.24 but 78,479 in the summary; miles 8,100 while the car expense stayed 8,260 | Every filed line now carries a **basis**, and nothing affected by an adjustment is shown as the engine's figure. `linear_terms()` reads, from the engine's own figures, which lines are fixed combinations of their inputs: sums, signed sums (SchC.31 = 29 − 30, AGI = F1040.9 − F1040.10), carries, and parameter conversions (SchC.9 = miles × 0.70). `derive_lines()` carries each adjustment through those lines exactly (**derived**: SchC.9 = 5,670). It sets the summary lines F1040.24 / F1040.37 / F540NR.64 / F540NR.97 to the same rate-based estimate as the filed summary (**estimate_rates**). Every other affected line, such as a tax computation, is marked **not_recomputed**: the engine figure is kept and labelled as such. Examiner Mode shows the basis on the item and on each input, with a red banner for not recomputed | `test_filed_lines_agree_with_the_filed_summary`: summary lines equal the filed summary; **every exact-combination line equals that combination of its inputs' filed values** (over 50 lines checked); SchC.9 5,670; SchC.31 moves by +2,590 − 12,400; no affected line has basis "engine" |
| P1 | Reopen after client approval was a dead end: the scripted approval was spent, and the next scripted event needed a submission | Once the scripted approval (tl-20) has been used, the client approves again **in TaxProof** (`POST /api/filing/client-approval`, clients only, explicit confirmation). It is checked against the partner's re-approval fingerprint and recorded as a `client` event. Staff see "Waiting for the client to approve…"; the client's Filing page shows "Approve and sign". Before tl-20 is replayed, in-app approval is refused (the script comes first) | `test_reopening_after_client_approval_has_a_way_forward`: approve → reopen → partner approves again → replay refused → the client approves in-app → submit → rejection → resubmit → filed |
| P1 | Approval independence only checked the draft's creator | Amendments and notice responses track **contributors** (create/change, assemble/edit). Anyone who contributed is refused approval: "You contributed to this amendment…" | `test_nobody_approves_what_they_contributed_to`: the partner edits, then the partner's approval is refused, for both an amendment and a notice response |
| P2 | Filing an amendment left the summary totals unchanged | Filing an amendment adds its estimated effects to the snapshot's totals (tax and balance), re-derives the lines from the amended ones, and recomputes `filed_summary`. Examiner Mode reads the new totals | `test_a_filed_amendment_moves_the_totals_too`: totals move by the amendment's effect; SchC.28 moves by the change; the consistency check passes on the amended snapshot; the original's hash is unchanged |

- Each new test was confirmed to **fail with its fix undone** (derivation off; totals not updated; creator-only
  check; no in-app approval).
- Clients no longer see the internal readiness and firm-steps panels on the Filing page.
- **Browser check:**
  - Reopen after client approval, then partner re-approval. As Ngozi, "Approve and sign" moves the return to
    Client Approved, and it is then filed.
  - The certificate's filed summary equals the line values (78,479 / 737).
  - In Examiner Mode, SchC.9 shows "recomputed exactly 5,670 (engine 8,260)". F1040.16 shows "NOT
    recomputed" with its reason and the adjustments behind it.
- Tests: **201 backend** (SQLite and PostgreSQL; the two filing modules each use their own database) and
  **29 frontend**.

## Iteration 9: AI Reviewer and firm intelligence ✅

**Goal:** AI only where structured, trustworthy context already exists. Every AI statement is grounded in
cited evidence or rejected; risk is explained, not a confidence number; the firm can set its own standards
and see its time.

### Delivered
- **Grounding layer** (`services/ai.py`).
  - **Context.** Tasks get a context of numbered facts, each with its supporting references and the
    numbers it contains, built deterministically and **masked** before anything leaves the server.
  - **Output.** The model must answer with claims that cite references.
  - **Validation.** Every claim is rejected unless:
    - it cites at least one reference;
    - every cited reference was in its context (it cannot introduce evidence);
    - every material number in the text appears in the cited facts;
    - it does not claim to have taken an action ("I adjusted / resolved / approved / filed…").
  - **Rejected claims** are shown apart, struck through, with the reason; they are never presented as
    findings.
  - **Run log.** Every run is stored in `ai_runs` (context hash, provider, model, claims, rejected count)
    and audited.
  - **Read-only.** No AI endpoint writes to the workpaper.
- **Providers.**
  - **Claude.** A Claude model (`TAXPROOF_AI_MODEL`, default `claude-opus-5-5`) is used only when
    `TAXPROOF_AI_API_KEY` is set. TaxProof does not borrow other credentials from its environment.
  - **Without a key,** the **grounded template** writes sentences from the same facts and is labelled
    "deterministic — no AI model" everywhere; it never passes itself off as AI.
  - **On failure,** a failed model call falls back to the template and says so.
- **AI Reviewer Brief** (Review → AI Reviewer). Not a chatbot: one ranked brief built from the
  risk-scored open items, covering suspicious evidence, missing documents, unexplained differences,
  variances, conflicts, incomplete verification and risky judgments. Every sentence links to its evidence.
- **Explain this finding** (Challenge drawer, replacing the Iteration 9 placeholder). It uses only the
  finding, its breakdown, the cited page text and its effect.
- **Draft with AI** (Ask client). It drafts a client question for the preparer to edit; a rejected draft is
  never inserted.
- **Review Risk Score** (`services/risk.py`, `/api/review/risk`). Nine named components:
  - extraction uncertainty
  - source conflict
  - duplicate evidence
  - prior-year variance
  - missing expected evidence
  - calculation disagreement
  - questionnaire contradiction
  - material tax impact (against the firm's partner threshold)
  - missing verification

  The score is their sum, capped at 100 (high ≥ 50, medium ≥ 25). Each component gives its points, a reason
  and its references. Areas are ranked by their highest item. On this packet: Paywell 80, California
  payments 72, mileage 70…
- **Search** (`/search`, new nav item).
  - **Computed answers** for recognised questions:
    - "why did tax increase from v2 to v3?" → Time Machine drivers, +4,492 / +875
    - "unresolved basis issues" → open inbox items about basis
    - "low-confidence extractions" → values below 80% and the lines they reach
  - **Everything else:** BM25 over lines, documents, pages, values, client answers, messages, call notes,
    timeline, findings, diagnostics and judgments, with a tax-concept lexicon. "California move" also
    searches residency, part-year, Texas and Sacramento, and every hit shows what matched.
  - All text is masked. There is no external embedding service, and the page says so.
- **Firm standards** (`firm_standards`; Firm page).
  - **Versions.** Version 0 is the packet's starter standards. The firm administrator saves new versions
    with a reason; each is validated and audited (before and after).
  - **What reads them:** variance review (area summaries, prior-year comparisons), the **partner threshold**
    (adjustments, judgments, Challenge findings, risk) and the **verification methods** offered and
    accepted.
  - **Existing records** keep the standard they were made under.
- **Budget vs actual** (`time_entries`; Firm page). Staff log quarter hours against the packet's budget lines;
  each line shows actual vs budget, who logged it, and "over budget".
- **Masking, access log and unmask logging** (Iterations 1–7) also cover every new response: search, AI runs
  and contexts, risk reasons.

### Tests
- **Backend:** 209 tests (8 new in `test_ai_intel.py`), passing on SQLite and PostgreSQL. They cover:
  - each validator rule
  - a hallucinating provider: grounded claims kept, foreign evidence and action claims rejected,
    **nothing in the workpaper changed**, run logged and audited
  - a failing provider falling back with a notice
  - **only masked context sent to the model** (the HTTP payload is checked for SSNs)
  - explanation and draft without a model
  - risk scores equal to the sum of explained components
  - the four example questions; masked search results
  - standards: role, validation, versioning, and taking effect (a 4,402 adjustment becomes reviewer-level at
    a 5,000 threshold; a removed method is refused); restored afterwards
  - time logging rules
- **Frontend:** 33 tests (5 new in `ai.test.tsx`):
  - grounded vs rejected claims with evidence links
  - the "no AI model" label
  - explain-on-request
  - risk components on demand
  - over-budget flag

### Limitations
- **No AI by default.** No model is configured in this environment, so the narrative is the grounded
  template. With a key, the same validator applies.
- **Search is not embedding-based.** It is lexical, with a hand-written concept lexicon plus associations
  learned from co-occurrence in this file. Embeddings (pgvector, or LSA with numpy) would replace the
  ranking step.
- **Rule text is not rewritten.** Rule wording is the firm's text: changing the partner threshold does not
  rewrite the sentence "over 1,000"; the administrator edits both.
- **Standards live in memory per process.** They are loaded at startup and replaced on save; with several
  worker processes, others would see the change after a restart.

### Review follow-ups (after the Iteration 9 review)
| # | Issue | Fix | Regression test |
|---|---|---|---|
| P1 | The validator accepted contradictory claims: +1,222 against a stated −1,222, and "all evidence is verified and the return is ready to file" citing unrelated mileage evidence | Three further checks. **Sign and direction:** a number may not contradict an explicitly signed number in the cited facts ("+1,222", or "increases by 1,222", against −1,222); plain magnitudes such as "3,700 miles" constrain nothing. **Status assertions:** verification, readiness, completeness ("all", "every", "no issues") and approval words must appear in the cited facts. **Support:** at least a third of a claim's content terms must appear in its cited facts ("says things not stated in the cited evidence"). Questions (drafts) are exempt from the last two but not from references, numbers and actions | `test_a_cited_fact_must_actually_support_the_claim`: 7 claims, including both reported cases and the legitimate paraphrases that must still pass ("falls by 1,222", "-1,222") |
| P1 | Firm standards returned an SSN typed into a rule or change note, unmasked, to an uncleared user | `/api/firm/standards` and `/api/firm` mask their whole payload, like every other free-text response | `test_firm_standards_are_masked_for_everyone` (standards, firm, audit and time-budget views; 4 users). Confirmed to fail without the fix |
| P2 | "Explain" always explained the v3 finding | The API takes the version (default: current) and explains that version's finding, saying which version and outcome ("In return version v1, TaxProof's check passed"); the subject is recorded as `finding:…@v1`. The Challenge drawer sends the version on screen | `test_explanations_follow_the_selected_return_version` (v1 pass vs v3 fail; unknown version 404) + frontend body check |
| P2 | Malformed model output (`claims: [null]`) raised an error | Each malformed claim is rejected ("malformed claim"); a non-list is treated as no claims; when a model returns nothing usable, the run falls back to the grounded template and says why | `test_malformed_model_output_is_rejected_safely_or_falls_back` |
| P2 | Judgments' (and approvals') tax exposure was missing from the risk score | A judgment item's material-tax-impact component uses its **tax at stake**; an adjustment-approval item uses the adjustment's estimated effect | `test_judgments_and_approvals_carry_their_tax_exposure_into_risk` (3,633 at stake → 25 points) |
| P2 | Accepted client answers were not searchable | Workpaper evidence is searched live: accepted client answers, judgments, adjustments and notes (masked) | `test_accepted_client_answers_are_searchable` (a unique phrase finds the answer first) |
| — | Found while fixing: a standards save could collide with an existing version number after the in-memory version fell behind the database | `save()` reloads from the database and numbers the version from it | covered by the standards tests running after a reset |

- **Semantic search (requirement gap).** Search now also uses **term associations learned from this file**:
  pointwise mutual information of co-occurrence across documents, pages, answers and notes, weighted low
  (0.25) and shown on the Search page as "learned from this file". It is distributional, but it is still
  not an embedding model; the associations are noisy (mileage-log destinations dominate "Sacramento"). A
  true embedding layer needs a new dependency or service (pgvector + an embedding model, or numpy for LSA)
  and is left as a decision.
- **Browser check:** the v1 California-wages finding explains as "passed in v1", citing the v1 line and the
  two W-2 state-wage readings.
- Tests: **216 backend** (SQLite and PostgreSQL) and **33 frontend**.

#### Semantic layer (decision: numpy + LSA, not pgvector)
- **What:** `services/semantic.py` learns a 48-dimension latent space from this packet by latent semantic
  analysis. It takes TF-IDF over the narrative objects (documents, pages, client answers, messages, call
  notes, timeline, findings, diagnostics, household) and applies a truncated SVD. It drops function words,
  numbers and object ids. Extracted values, return lines and live workpaper objects (accepted answers,
  judgments, adjustments, notes) are folded into the same space. The space is built from the already-masked
  search text at startup (`search.warm`) and cached by packet hash. No model, API key or service is involved,
  and nothing leaves the server. The only new dependency is `numpy==2.2.6`.
- **Blend:** `rank` keeps the intent handlers, the lexicon and the PMI associations. The final score is
  70% BM25 (normalised by the query's best hit) and 30% semantic. The semantic part is the cosine similarity
  above a floor of 0.45; anything below the floor adds nothing. The query vector carries the same weighted
  terms as BM25: query words, lexicon concepts and learned associations.
- **Explanations:** every hit keeps `matched` (lexical terms) and adds `semantic` (the cosine) and `related`
  (the hit's words closest to the query in the latent space). The page shows "no shared words · semantically
  related (0.83): ada, student, tuition". The method line now says what was used, and says so honestly when
  the layer is unavailable.
- **Fallback:** if numpy is missing or the layer fails, search runs on BM25 alone and the method line says
  "Semantic layer unavailable". The database is not involved, so SQLite and PostgreSQL behave the same.
- **Effect:** "relocation to Texas" puts qa-02 ("Sacramento to Austin", which shares no words with the
  query) at #4, up from #5. "university" puts the D60 scholarship letter at #4, up from #302. The letter
  matches no query word, lexicon concept or association.
- **Limits:** the space is learned from one file of about 400 narrative objects, so it only knows words that
  appear in the packet. Words outside the vocabulary ("daycare", "college") get no semantic signal. On this
  corpus, LSA mainly reorders hits that already match. pgvector with an embedding model remains the upgrade
  path, at the `_semantic` step.
- Tests: `test_semantic_layer_finds_answers_that_share_no_words` (also proves that switching the signal off
  drops the D60 hit out of the top 5), `test_search_falls_back_to_bm25_without_the_semantic_layer` (numpy
  absent; layer raising), and `test_search_api_reports_the_semantic_method_and_stays_masked`.
  **219 backend** (SQLite and PostgreSQL) and **33 frontend**.

## Iteration 10: Return Assurance Twin ✅

**Goal:** unify everything into one product: **TaxProof — Return Assurance Twin**. The supplied engine produces
the return; TaxProof independently assembles the assurance record around it and says, at any moment, how far
the return is proven and exactly what prevents filing.

### Delivered
- **Assurance twin** (`services/twin.py`, `api/twin.py`). Every figure is computed from the packet and the
  workpaper, none by a model:
  - **Documents accounted for:** used, superseded, or not used for a recorded reason (D71 and D72 arrive after
    v3); document-level reading issues are listed.
  - **Material lines traceable:** lines of 1,000 or more whose inputs reach cited evidence (272 of 274 on v3).
  - **Evidence coverage:** values feeding the return that a person verified.
  - **Independent checks:** passed, or failed / needing judgment but dispositioned.
  - **Judgment completion, review, partner, client authorization** of the exact content on file.
  - **Filing readiness and critical issues** (high review-risk items).
- **Return assurance score.** A weighted sum of nine ratios:
  - documents 10
  - traceability 15
  - coverage 10
  - checks 20
  - judgments 10
  - review 10
  - partner 10
  - client 5
  - no blockers 10

  Each component shows its points, reason and a link. It is explicitly not a probability or a model's
  confidence. On the packet: 48 ("weak") untouched → 90 ("strong") once decided, signed, approved and filed.
  The remaining 10 points are evidence coverage, because nobody verified individual values in the walkthrough.
- **Dashboard** (Overview, renamed **Return Assurance Twin**; shell and page title rebranded):
  - federal and California tax with balance or refund, the engine's figures, plus an "As filed" /
    workpaper-estimate strip when adjustments apply
  - the prior-year comparison
  - the score dial and its components
  - "What prevents filing?"
  - eight tiles: evidence coverage, independent checks, areas reviewed, judgments, documents, sign-offs
    complete, filing readiness, critical issues
  - critical issues
  - **since you last looked**
  - packet integrity
  - the **six signature features** (Prove It, Challenge Return, Return Assurance Twin, Tax Time Machine,
    Living Sign-offs, Examiner Mode)
- **Since you last looked** (`view_marks`). Each person marks the dashboard seen. They then see what *others*
  changed since (grouped: sign-offs, filing, adjustments, notes…, plus the latest events), taken from the
  audit chain. Noise (permission denials, AI runs, report views) and their own actions are left out.
- **"Why should I trust this return?"** (`/trust`, also from the dashboard header). A structured report
  answers nine questions:
  - documents accounted for
  - material lines traceable
  - independent checks
  - unresolved issues
  - judgment calls documented
  - review completion
  - partner completion
  - client authorization
  - filing status

  Each answer comes with a status, how it was computed, the exceptions, and a link to the proof. Then comes
  **"What prevents filing?"**: every failing gate check with its items, then each lifecycle step still ahead
  (e.g. "Client approval and Form 8879 (the client approves again in TaxProof)"). The verdict is either
  "N thing(s) prevent filing" or "Filed and defended: nothing prevents filing." The report ends with the
  closing statement and carries a content hash; generating it is audited.
- **Partner summary.** A grounded narrative of the trust report (Iteration 9 validator: every sentence cites
  `twin:<section>`).

### Demo path (all in the app)
1. **Overview.** "The return engine says the return is computed. TaxProof asks whether it is proven." Score 48.
2. **Challenge.** The mileage duplicate (D23 pages 2 and 3); Prove It on SchC.44a shows both pages flowing
   into 11,800.
3. **Adjust.** Create & apply −3,700 miles: estimated +919 / +80, and the Business reviewed and partner
   sign-offs reopen with the reason. The Paywell 12,400 duplicate gets the same treatment.
4. **Tax Time Machine.** v2 → v3: +4,492 / +875 and the six driver lines.
5. **Review.** As Daniel, raise or resolve a review note; the inbox, judgments and sign-offs follow.
6. **Trust report.** As Helen, open "Why should I trust this return?" and its exact blockers.
7. **Filing.** Replay client approval and Form 8879, then submit. The e-file rejection (Theo's TIN — flagged
   by TaxProof before filing) is followed by the corrected evidence (D71), resubmission, federal and
   California acceptance, and record as filed (immutable snapshot, certificate).
8. **Examiner Mode.** Jump to the 2028 Letter 566. Examiner Mode reconstructs SchC.1 and SchA.12 from the
   filed snapshot; assemble the response package and have the partner approve it.
9. **Close.** The trust report: "Filed and defended", score 90, and the closing line.

### Tests
- **Backend:** 225 tests (6 new in `test_twin.py`), passing on SQLite and PostgreSQL. `test_twin.py` runs on
  its own database through every state, from preparing → decided → signed → filed. It covers:
  - weights summing to 100
  - the score equal to its components
  - honest starting values: 74/74 documents, nothing reviewed, gate checks and lifecycle steps listed
  - the trust report's nine questions, the verdict, the closing line, a stable report hash and its audit
    event
  - a grounded summary with nothing rejected
  - since-you-last-looked: others' changes grouped, own actions excluded, reset on "seen"
  - the score rising monotonically as the work is proven, ending filed with nothing preventing filing and
    "Filed and defended"
  - no full SSN on twin views
- **Frontend:** 36 tests (3 new in `twin.test.tsx`): dashboard score, components, blockers, critical issues,
  since-you-looked and mark-seen; "Nothing prevents filing."; the trust page's answers, blockers, closing
  statement and summary.

### Limitations
- **Evidence coverage** counts per-value verifications. Verifying a line does not count its values, so
  coverage stays low unless reviewers verify values.
- **"Since you last looked"** is per person and per dashboard, not per area.
- **Trust reports are not stored.** They are regenerated on demand, and their hash is in the audit chain.
- **The score's weights** are the firm's to tune. They are fixed in code here; standards versioning
  (Iteration 9) would be the place to move them.

### Review follow-ups (after the full review)
| # | Issue | Fix | Regression test |
|---|---|---|---|
| P1 | The AI validator accepted negated findings ("page 3 does not duplicate page 2") and swapped figures ("the engine has 8,100, TaxProof 11,800") | Two more checks. **Negation:** a claim may not negate its relevant cited facts (those sharing at least 40% of its terms), nor drop a negation they state ("D71 was used" against "D71 was not used"). **Roles:** a number the claim attributes to the engine (or to TaxProof's independent value) must not be the other one in the cited evidence | `test_negated_and_swapped_claims_are_rejected` (7 claims, including the legitimate forms that must still pass); every grounded output in the suite still passes |
| P1 | The trust report stayed green when a filed snapshot no longer matched its hash | The twin verifies **every** snapshot. Any failure becomes the first item under "What prevents filing", turns the filing answer red ("the filed record does not match its hash … altered after filing"), changes the verdict ("Filed, but the filed record fails its integrity check"), zeroes the no-blockers component and sets `can_file_now` false | `test_a_tampered_snapshot_turns_the_trust_report_red_and_blocks_amendments` (and back to "Filed and defended" once restored) |
| P1 | An amendment could copy a corrupted snapshot into a newly hashed one | Creating and filing an amendment both refuse while any filed snapshot fails its integrity check | the same test plus `test_an_amended_snapshot_must_come_from_an_intact_base` |
| P1 | One amendment could change a line and a line computed from it, counting one correction twice | `add_change` refuses a line in the same flow path as another change in the amendment (either direction), naming the other line; replacing the same line is still allowed | `test_one_amendment_cannot_change_a_line_and_a_line_computed_from_it` |
| P2 | The dashboard said 8 critical issues when there were 10 | The twin returns `critical_count` (all high-risk items) beside the first eight it lists. The tile and the panel title show the full count, with "all N →" | `test_the_dashboard_counts_every_critical_issue` + frontend assertion |
| P2 | Tests shared one database: reversing the file order caused 7 failures | **Every test module gets its own fresh database** (`conftest.isolated_client`: a new SQLite file, or its own PostgreSQL schema), migrated and seeded; process-wide standards follow it and are reset afterwards. Tests that touched the database directly use the module's session | the whole suite in forward **and reversed** file order, and every test file **on its own**, on SQLite and on PostgreSQL |

- Tests: **230 backend** — forward and reversed order, on SQLite and on PostgreSQL, and each file alone — plus
  **36 frontend**.

### Done
All ten iterations are complete.

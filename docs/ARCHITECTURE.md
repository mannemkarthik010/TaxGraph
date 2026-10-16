# TaxProof — Architecture (Iteration 1 baseline)

> AI investigates. Code calculates. Evidence proves. CPAs decide.

## 1. The supplied packet (`okafor_lindqvist_2025_packet.json`)

Treated as **immutable pipeline output**. It is loaded once, hashed (SHA-256), deep-frozen in memory
(`FrozenDict` / tuples — any mutation raises `TypeError`), and never written back.

| Section | Shape | IDs |
|---|---|---|
| `packet` | name, version, generated, client_id | `CL-20417` |
| `readme` | field definitions + reference formats | — |
| `household` | filing status, 4 people, addresses, residency (CA → TX 2025-07-15), refund bank, related returns | `household:<person id>` (`ngozi`, `erik`, `ada`, `theo`) |
| `documents[74]` | metadata, `pages[{page, printed_content}]`, `extraction{status, values, reason}`, `marked_corrected` | `D01..D74`, `doc:Dxx#pageN` |
| `extracted_values[3012]` | document_id, page, field, label, value, value_type, text_as_read, position{x0..y1}, confidence | `ev-NNNN` |
| `client.questionnaire[45]` / `messages[10]` / `call_notes[1]` | client facts | `qa-NN`, `msg-NN`, `call-NN` |
| `firm` | staff[6], client_users[2], assignment, deadlines, budget hours, starter standards | `st-0N`, `cu-0N` |
| `prior_years` | 2024 return lines (+ `line_sources` → ev ids on D06), prior preparer memo, asset/basis records, carryovers | `py:/<json pointer>` |
| `tax_agency_records` | IRS transcripts, FTB account, notices, e-file submissions | `agency:/<json pointer>` |
| `timeline[29]` | scripted season events | `tl-NN`, `extension-2026-04-14` |
| `engine_reference` | parameters + rule descriptions | `ref:param.<name>`, `R-*` |
| `return_versions[3]` | v1/v2/v3: summary, tax_effect_rates, assets, diagnostics, changes_from_previous, ~625 lines | line keys `<form>.<line>` |
| `what_if` | engine-computed alternatives + April extension estimate | `id` |

### Relationships discovered
- `return_line.sources[]` → `ev-*`, `ref:param.*`, `py:/…`, `asset:*`, `qa-*` … (heterogeneous refs → universal resolver)
- `return_line.inputs[]` → other line keys **in the same version** (a calculation DAG)
- `extracted_value.document_id + page` → `documents[].pages[]`
- `return_versions[].documents_used / documents_superseded` → documents
- `timeline[].refs` → docs, messages, versions, agency pointers
- `diagnostics[].refs` → ev ids, line keys, qa ids
- `prior_years.return_2024.line_sources` → ev ids on D06 (prior-year continuity)

Already visible "confident mistakes" (to be surfaced by later iterations, not hard-coded):
`SchC.44a = 11,800` built from 4 page totals of D23 (pages 2 & 3 are the same May–Aug sheet);
`SchC.1 = 163,700` = books + "unmatched" 1099-K; Theo's SSN read as `666-74-3390` on D71/ev-0012
vs `666-74-3309` in the organizer (later e-file rejection).

## 2. Layering

```
packet JSON (immutable, hashed)
  └─ PacketIndex           backend/app/packet/       read-only indexes + universal ref resolver
       └─ Workpaper layer  backend/app/models.py     mutable rows in PostgreSQL, reference packet by ref string
            └─ Services    backend/app/services/     audit chain, masking, permissions, return views
                 └─ API    backend/app/api/          FastAPI, server-side RBAC via X-TaxProof-User
                      └─ UI frontend/                Next.js App Router + Tailwind + shadcn/ui
```

The workpaper never copies packet values into its own tables; it points at them with the packet's own
reference grammar (`ev-0226`, `line:v3:SchC.44a`, `doc:D23#page2`, `household:theo.ssn`). This is what lets
later iterations attach verifications, adjustments, judgments and sign-offs to *any* node.

## 3. Folder layout

```
TaxGraph/
  okafor_lindqvist_2025_packet.json   ← untouched
  docker-compose.yml                  ← PostgreSQL 16
  backend/
    app/
      main.py  config.py  db.py  models.py  deps.py  bootstrap.py
      packet/   loader.py (freeze + hash)  index.py (indexes)  refs.py (resolver)
      security/ roles.py (permission matrix)  masking.py
      services/ audit.py  returns.py  variance.py
      api/      session.py engagement.py returns.py documents.py workpaper.py firm.py
    alembic/  (migrations)
    tests/
  frontend/
    src/app/(workpaper)/{overview,evidence,return,review,timeline,filing,firm}
    src/components/  src/lib/
  docs/
```

## 4. Iteration 1 database schema

| Table | Purpose | Key columns |
|---|---|---|
| `engagements` | one return engagement per packet | id, client_id, tax_year, name, packet_sha256, packet_version, status, as_of |
| `users` | firm staff + client users (seeded from packet, then owned by the workpaper) | id (`st-01`…), name, role, credential, sensitive_data_clearance, kind, active_from |
| `engagement_assignments` | who plays which role on this engagement | engagement_id, user_id, role, assigned_at, source |
| `workpaper_areas` | the 11 tax areas (Employment … Carryovers) | key, title, budget_key, prepared/reviewed/partner status (iteration 7 drives these) |
| `workpaper_notes` | first mutable workpaper record: notes / review notes on any ref | target_ref, kind, body, visibility, status, blocking, author, resolved_by |
| `audit_events` | append-only, **hash-chained** event log | seq, at, actor, role, action, target_ref, payload, prev_hash, hash |
| `access_logs` | every sensitive reveal (granted or denied) | user, field_ref, granted, reason, at |

| `verifications` *(Iteration 2)* | how a value, line, document or page was checked | target_ref, method, note, evidence_refs, acknowledged_flags, verified_by, status (active/withdrawn) |

| `evidence_links` *(Iteration 3)* | relationships people assert between graph nodes | src_ref, dst_ref, type, note, created_by, status (active/retired) |

| `adjustments` *(Iteration 6)* | workpaper changes to a line; the engine value is never overwritten | version, target_line, original_value, adjusted_value, difference, unit, reason, evidence_refs, finding_id, status (proposed/applied/undone), review_required, effect (estimate), created_by, approved_by, history |

The evidence graph itself is derived, not stored: packet nodes/edges are rebuilt from the immutable
packet (cached by its hash) and the workpaper tables above are overlaid per request.

| `issues` *(Iteration 7)* | people's decisions about an Uncertainty Inbox item (the items themselves are derived) | item_key (`finding:…`, `note:12`, `diag:CODE`, …), status (open/resolved/accepted), escalated, assignee, resolution_kind, resolution, resolved_by, history |
| `client_questions` *(Iteration 7)* | questions to the client; an accepted answer is evidence | item_key, target_ref, question, blocking, addressed_to, status (asked/answered/accepted/withdrawn), answer, answered_by, accepted_by, resolves_item, history |
| `judgments` *(Iteration 7)* | the Judgment Ledger; revised by superseding | topic, target_refs, area_keys, decision, decision_option (keep_engine/what_if:id/other), alternatives, rationale, authority, evidence_refs, tax_effect, review_required, status (recorded/reviewed/approved/superseded), prepared/reviewed/partner by + at, supersedes_id |
| `signoffs` *(Iteration 7)* | living area sign-offs; reopened, never deleted | area_key, level (prepared/reviewed/partner), version, signed_by, open_items_at_signing, status (active/reopened), reopen_reasons [{at, by, action, ref, detail}] |

Graph overlay (Iteration 7): `judgment:N` nodes (RELATED_TO the lines they decide) and `client_answer:N`
nodes (the line or document they are about is CONFIRMED_BY them), staff only.

| `filing_events` *(Iteration 8)* | append-only filing lifecycle log: firm actions and replayed client/agency events | at (scripted or replay-clock time), kind (action/replay), action, timeline_id, from_state, to_state, actor, note, detail (fingerprint, submission package + hash, e-file submissions, correction, amounts, notices) |
| `filed_snapshots` *(Iteration 8)* | the return exactly as filed or amended; written once, never updated | kind (original/amendment), number, base_snapshot_id, version, filed_at, content, content_sha256 (also in the audit chain) |
| `amendments` *(Iteration 8)* | changes to a filed return; filing one creates a new snapshot | base_snapshot_id, reason, changes [{line, filed_value, amended_value, difference, effect}], status (draft/approved/filed/withdrawn), approved_by, filed_snapshot_id |
| `notice_responses` *(Iteration 8)* | agency-notice response packages assembled from the filed record | notice_id, snapshot_id, items [{text, lines, explanation, exhibits}], cover_letter, status (draft/approved), approved_by, content_sha256 |

`engagements.status` holds the filing lifecycle state. Write locks (`api/locks.py`): from submission on the
return's content (adjustments, judgments, sign-offs) is locked; a frozen workpaper accepts only amendments
and examination responses.

| `ai_runs` *(Iteration 9)* | every AI call: masked context and hash, provider/model, validated claims | task, subject, provider, model, context_sha256, context, raw_output, claims [{text, refs, status, problems}], supported, rejected, error |
| `firm_standards` *(Iteration 9)* | versions of the firm's standards (version 0 = packet starter) | version, content (variance_review, partner_threshold, verification_types, rules, required_steps), note, changed_by |
| `time_entries` *(Iteration 9)* | time against the firm's budget lines | user, budget_key, hours (quarter hours), worked_on, note |

| `view_marks` *(Iteration 10)* | when a person last looked at the dashboard | user, scope, seen_at, seen_seq (last audit event seen) |

The Return Assurance Twin itself (`services/twin.py`) is derived: every dashboard figure, the assurance score
and the trust report are computed on request from the packet and the tables above.

Not built: `notifications` (the dashboard's "since you last looked" covers the prototype's need).

## 5. Roles and enforcement

The role switcher picks an **acting user** (not a free-form role), so firm rules that depend on identity —
"a preparer cannot review their own work", "Marcus has no sensitive-data clearance" — are real. The
frontend sends `X-TaxProof-User`; the server resolves the user and checks a permission matrix in
`security/roles.py`. Denials return 403 and are audited.

Iteration 7 permissions: `ask_client`, `record_judgment` (preparer, reviewer, partner); `review_judgment`
(reviewer, partner); `sign_prepared` (preparer, reviewer, partner), `sign_reviewed` (reviewer, partner),
`sign_partner` (partner); `answer_client_question` (client). Identity rules (nobody reviews or signs work
they prepared) are checked against the actual users, not the role.

Sensitive values (SSNs, IP PINs, bank/account numbers, e-signature PINs, and SSN/IBAN patterns inside
`printed_content`) are **masked for everyone by default**. Cleared staff and the clients themselves can
reveal one field at a time; every reveal and every denied attempt is written to `access_logs` and the audit chain.

## 6. Assumptions

1. "Now" is v3 (2026-06-23) per the README; later timeline events are replay material (iteration 8).
2. The packet's staff roster is the user directory; the firm administrator may later edit the workpaper copy.
3. Auth is simulated (header-based acting user) — appropriate for a screening prototype; RBAC is still server-side.
4. Default DB is PostgreSQL via docker compose; `DATABASE_URL=sqlite:///…` is supported for tests and zero-dependency runs.
5. Money in return lines is whole dollars except F8949 lots (cents), per the README.

# Tanishk — Implementation Plan
## Approach: Deterministic Policy Engine + LangGraph State Machine ("Explainable-First")

---

## 1. Philosophy & Scoring Alignment

A real fraud decision must be auditable and reproducible, not a single LLM free-associating over a policy document. This design treats the LLM strictly as an **evidence synthesizer and writer** (pattern naming grounded in retrieval, prose for `summary`/`sar.narrative`), while every `action` + `route` recommendation is produced by a **deterministic Python rules engine** that is a line-by-line transcription of the hackathon's Fraud Policy (R1–R10). This directly targets:

- **Next best action (25%)** — actions are rule-derived and testable, not hallucinated.
- **Case summary & explainability (10%)** — every action carries an explicit rule citation traced back to code, not just a prompt.
- **Agentic design & engineering (15%)** — the policy engine ships with unit tests, one per rule, which is verifiable engineering rigor a judge can open and read.
- **Investigation accuracy (25%)** — evidence gathering is exhaustive and structured (parallel GSQL calls per case) rather than left to the LLM to decide what to look up.

This plan strictly follows the hackathon's required components: TigerGraph (Savanna/CE) for graph + vector storage, GSQL + graph algorithms, TigerGraph MCP, GraphRAG (grounded context, not raw data), and a user interface demonstrating investigation, case progression, evidence, uncertainty, recommendations, and next actions. Agent framework and LLM choice are explicitly optional per the task PDF — LangGraph and Groq are the choices exercised here.

---

## 2. Full Tech Stack

| Layer | Choice | Justification |
|---|---|---|
| Graph + vector DB | **TigerGraph Community Edition** (self-hosted via Docker, reachable from the Render backend), Savanna as a fallback | Required by the hackathon. CE gives zero-cost, full-control iteration with no auto-stop concerns |
| Agent orchestration | **LangGraph** (Python) | Matches the README's 8-step investigation flow as an explicit, inspectable state graph rather than an implicit chat loop |
| Graph tool access | **TigerGraph MCP server** (https://github.com/tigergraph/tigergraph-mcp), wrapped as LangGraph tools | Required component — exposes GSQL queries as callable tools for the agent |
| LLM | **Groq API, free tier** — `llama-3.3-70b-versatile` for evidence synthesis/pattern-labeling/SAR prose, `llama-3.1-8b-instant` for cheap classification sub-steps (e.g. single-signal check) | Free tier, very low latency (relevant because `latency_s` is a graded field), OpenAI-compatible chat completion API |
| Auxiliary database | **Supabase (Postgres)** | Not specified by the hackathon — TigerGraph is mandatory only for the graph/vector layer. Used for: case-answer-file mirrors, simulated evidence-response configs, audit/event logs |
| Backend API | **Python FastAPI** | Hosts the LangGraph agent, TigerGraph MCP client, Groq calls, Supabase client; exposes REST endpoints to the frontend |
| Frontend | **TypeScript, Next.js (App Router)** | Renders Case Feed, Investigation Trace, and Graph View |
| Frontend data layer | **Supabase JS client** (read-only, anon key) for case list/status, typed REST calls to FastAPI for live investigation triggers and traces | Keeps the read-heavy dashboard fast without hammering the backend on every page load |
| Hosting | **Frontend → Vercel, Backend → Render** | Per requirement |

---

## 3. Graph Schema (Detailed)

### Vertices

| Vertex | Key attributes | Populated from |
|---|---|---|
| `Customer` | `customer_id` (PK), `first_seen_ts`, `n_cards` | derived from `transactions.csv` |
| `Card` | `card_id` (PK), `customer_id`, `card_network` (card4), `card_type` (card6), `device_cluster_id`, `region_cluster_id` | `transactions.csv` card1–card6 |
| `Transaction` | `txn_id` (PK, TransactionID), `ts`, `amount`, `product_cd`, `channel`, `risk_score`, plus raw `C1–C14`, `D1–D15`, `M1–M9`, `V1–V339` as attributes | `transactions.csv` |
| `DeviceProfile` | `device_key` (PK = `DeviceInfo\|id_30\|id_31\|id_33` concatenated), `device_type`, `is_new_flag_seen` | `identity.csv` |
| `EmailDomain` | `domain` (PK) | `P_emaildomain`, `R_emaildomain` |
| `BillingRegion` | `region_code` (PK = addr1), `country_code` (addr2) | `transactions.csv` |
| `ClosedCase` | `case_id` (PK, e.g. CC-0001), `customer_id`, `card_id`, `opened_at`, `closed_at`, `outcome`, `pattern`, `first_fraud_txn_id`, `n_txns`, `exposure_usd`, `report_filed`, `analyst_notes` (embedded text) | `closed_cases_history.csv` |
| `Case` | `case_id` (PK, e.g. HHG-017), `status`, `verdict`, `fraud_probability`, `pattern`, `pattern_description`, `exposure_usd`, `summary`, `created_at`, `updated_at` | written by the agent |
| `PolicyChunk` | `rule_id` (PK, R1–R10), `text`, `embedding` | Fraud Policy section, one chunk per rule |
| `PatternChunk` | `pattern_id` (PK), `text`, `embedding` | The 5 documented pattern definitions |
| `RegDoc` | `doc_id`, `source_url`, `chunk_text`, `embedding` | Selected FinCEN/FATF/FFIEC references, chunked |

### Edges

```
Customer -(OWNS)-> Card
Card -(MADE)-> Transaction
Transaction -(NEXT)-> Transaction            // ordered by ts within a card, built via a loading job
Transaction -(FROM_DEVICE)-> DeviceProfile   // online only, from identity.csv join
Transaction -(PURCHASER_EMAIL)-> EmailDomain
Transaction -(BILLED_IN)-> BillingRegion
ClosedCase -(INVOLVES)-> Transaction
ClosedCase -(ON_CARD)-> Card
ClosedCase -(CONNECTED_TO)-> Card
Case -(OPENED_FOR)-> Transaction
Case -(AFFECTS)-> Transaction                // all affected_txn_ids
Case -(LINKS_CARD)-> Card                    // connected_card_ids
Case -(CITES)-> ClosedCase                   // similar_prior_cases
Case -(APPLIED_RULE)-> PolicyChunk           // rule citations, for auditability
```

`DeviceProfile.device_key` is a compound string so identical device fingerprints collapse into one vertex — shared-device detection becomes a neighbor-count query rather than a bespoke join.

---

## 4. Data Loading Pipeline (Detailed)

Run as a one-time job against the TigerGraph instance — not part of the request-serving API.

1. **Schema creation.** `schema/create_schema.gsql` defines all vertices/edges above with typed attributes (`STRING`, `DOUBLE`, `DATETIME`, `VECTOR` for embedding attributes at the configured dimension).
2. **Transactions load.** `etl/load_transactions.py`: stream `transactions.csv` in 50,000-row chunks (`pandas.read_csv(..., chunksize=50000)` — the file is ~708 MB and must not be loaded fully into memory). Per chunk:
   - Derive `customer_id` from `card1` per the dataset's documented derivation.
   - Upsert `Customer`, `Card`, `BillingRegion`, `EmailDomain` vertices (idempotent, to survive re-runs).
   - Bulk-insert `Transaction` vertices with all 393 original columns preserved plus `customer_id`, `ts`, `channel`, `risk_score`.
   - Insert `Card -(MADE)-> Transaction`, `Transaction -(BILLED_IN)-> BillingRegion`, `Transaction -(PURCHASER_EMAIL)-> EmailDomain` edges.
3. **Identity join.** `etl/load_identity.py`: read `identity.csv` fully (26 MB, fits in memory), left-join on `TransactionID`, upsert `DeviceProfile` vertices keyed by the compound device key, insert `Transaction -(FROM_DEVICE)-> DeviceProfile` edges. Only the ~144,432 online transactions get this edge; `W`-product-code (in-person) transactions correctly have none.
4. **NEXT-chain construction.** `build_next_edges.gsql`: for each `Card`, order its `Transaction`s by `ts` and insert `Transaction -(NEXT)-> Transaction` edges between consecutive pairs. Powers the card-testing window query (R5) without per-request sorting.
5. **Closed cases load.** `etl/load_closed_cases.py`: read `closed_cases_history.csv` (5,565 rows, small), explode the pipe-separated `txn_ids` and `connected_card_ids` columns, insert `ClosedCase` vertices and `INVOLVES`/`ON_CARD`/`CONNECTED_TO` edges.
6. **Embedding + vector indexing.** `etl/embed_documents.py`:
   - Chunk the Fraud Policy section (R0–R10) into one `PolicyChunk` per rule.
   - Chunk the 5 pattern definitions into `PatternChunk` vertices.
   - Use each `ClosedCase.analyst_notes` field as its own chunk (already short — no further splitting needed).
   - Fetch and chunk the FinCEN SAR Narrative Guidance and Account Takeover Advisory documents (grounding for later SAR-writing).
   - Compute embeddings locally with a free sentence-embedding model (e.g. `sentence-transformers/all-MiniLM-L6-v2` — no API cost, runs on the Render instance or an offline batch machine) and write into each vertex's `embedding` vector attribute; build TigerGraph's native vector index over each chunk type.
7. **Case pack load.** `etl/load_case_pack.py`: load `case_pack.csv` as the 20 trigger records; also mirrored into a Supabase `case_pack` table so the frontend can list all 20 without a TigerGraph round-trip for a simple index view.
8. **Validation pass.** `etl/validate_load.py`: confirm every `flagged_txn_id` in the case pack resolves to a real `Transaction` vertex, confirm row counts match the README's stated counts (590,742 transactions, 144,432 identity records, 5,565 closed cases), and hand-verify 2 cases manually via GSQL before writing any agent code — per the README's own recommended first step ("investigate one case by hand").

---

## 5. GSQL Query Library (Tools Exposed via MCP)

| Query name | Purpose | Returns |
|---|---|---|
| `card_window(card_id, hours)` | All transactions on a card within a rolling time window, ordered via the `NEXT` chain | list of transactions with amounts/ts/product_cd |
| `device_neighbors(device_key)` | All cards/customers/transactions sharing a device profile, plus any `ClosedCase` touching that device | shared-device evidence |
| `region_cluster(region_code, window_days)` | Cards billed in a region with no prior history there, and any concurrent activity elsewhere for the same customer | out-of-region evidence (pattern 4) |
| `customer_baseline(customer_id)` | Historical spend pattern: typical amount range, typical product codes, typical channel mix | "does this fit the cardholder's history" check for pattern 2/3 |
| `closed_case_lookup(entity_ids)` | Graph traversal to `ClosedCase`s touching any of the given card/device/region IDs | direct-memory hits |
| `vector_search(query_text, chunk_type, k)` | Vector top-k over `PolicyChunk` / `PatternChunk` / `ClosedCase.analyst_notes` / `RegDoc` | GraphRAG retrieval |
| `write_case(case_json)` | Upserts a `Case` vertex + all edges (`AFFECTS`, `LINKS_CARD`, `CITES`, `APPLIED_RULE`) | confirmation + `graph_case_id` |

Each tool's return is wrapped 1:1 into an `evidence` object (`source="graph"`, `ref="query:<name>(<args>)"`, `entity_ids=[...]`) as required by the Answer Format — no manual reformatting needed downstream.

---

## 6. LangGraph State Machine (Detailed)

```
TRIGGER
  → LOAD_CASE_CONTEXT        (pull case_pack row, flagged transaction, card, customer)
  → GATHER_EVIDENCE          (parallel: card_window, device_neighbors, region_cluster, customer_baseline)
  → RETRIEVE_MEMORY          (vector_search over ClosedCase notes + closed_case_lookup graph traversal)
  → ASSESS                   (Groq LLM call, grounded ONLY on the evidence list already gathered)
       -> outputs: pattern, pattern_description (if undocumented), fraud_probability, rationale
  → SINGLE_SIGNAL_CHECK      (deterministic: is this resting on one signal only, e.g. risk_score alone?)
  → DECIDE_ACTIONS_INITIAL   (PolicyEngine.decide_initial(), no customer reply yet) → next_best_actions.initial
  → NEED_MORE_EVIDENCE?
       ├─ yes (R1 triggers VERIFY_WITH_CUSTOMER/STEP_UP_AUTH, or ambiguous evidence)
       │     → REQUEST_EVIDENCE (log evidence_requests entry, pull simulated response from Supabase config)
       │     → RE-ASSESS (Groq call with updated evidence)
       │     → DECIDE_ACTIONS_FINAL (PolicyEngine.decide_final()) → next_best_actions.final
       └─ no → next_best_actions.final = next_best_actions.initial
  → STOP_CHECK               (probability >=0.85 or <=0.15 with >=2 evidence sources, OR verification settled it,
                               OR marginal-gain check fails) → stop_reason
  → SAR_DECISION             (PolicyEngine.sar_decision() — deterministic, section 3a rules)
  → SAR_WRITE (if file=true)  (Groq call, grounded on FinCEN RegDoc chunks, six-to-twelve-sentence narrative)
  → WRITE_CASE_TO_GRAPH      (write_case tool call; mirrored into Supabase `cases` table)
  → EMIT_ANSWER_FILE         (Pydantic-validated JSON matching the Answer Format exactly)
```

State is a single typed Pydantic model carried through every node, matching the answer-file schema field-for-field, so serialization at the end is a no-op rather than a translation step.

### Deterministic Policy Engine (core differentiator)

```python
# policy_engine.py — pure functions, zero LLM calls, one test per rule in tests/test_policy_engine.py

def decide_initial(evidence: EvidenceBundle, probability: float, pattern: str) -> list[Action]:
    actions = []
    if evidence.is_single_signal and probability < 0.70:
        actions.append(Action("VERIFY_WITH_CUSTOMER", "auto", "R1"))
    if pattern == "card_testing":
        actions.append(Action("DECLINE_TRANSACTION", "L1", "R5"))
        actions.append(Action("STEP_UP_AUTH", "auto", "R5"))
        if evidence.large_purchase_cleared:
            actions.append(Action("BLOCK_CARD", route_for_exposure(evidence.exposure_usd), "R5"))
    if evidence.shared_origin_detected:
        actions.append(Action("CREATE_CASE", "auto", "R6"))
        actions.append(Action("FILE_REPORT", "L2", "R6"))
        actions.append(Action("MONITOR_CONNECTED_CARDS", "auto", "R6"))
    return dedupe(actions)

def decide_final(evidence, probability, pattern, customer_reply: str | None) -> list[Action]:
    actions = []
    if customer_reply == "denied":
        actions.append(Action("BLOCK_CARD", route_for_exposure(evidence.exposure_usd), "R2"))
        actions.append(Action("CREATE_CASE", "auto", "R2"))
        if evidence.exposure_usd > 1000 or evidence.shared_origin_detected:
            actions.append(Action("FILE_REPORT", "L2", "R2"))
    elif customer_reply == "confirmed":
        actions.append(Action("CLOSE_NO_FRAUD", "auto", "R3"))
    elif customer_reply is None and evidence.no_reply_24h:
        actions.append(Action("MONITOR_CARD", "auto", "R4"))
        actions.append(Action("DECLINE_TRANSACTION", "L1", "R4"))
        if evidence.exposure_usd > 500:
            actions.append(Action("ESCALATE_TO_ANALYST", "auto", "R4"))
    if evidence.is_recurring_disputed_but_matches_pattern:
        actions = [Action("CREATE_CASE", "auto", "R7"),
                   Action("VERIFY_WITH_CUSTOMER", "auto", "R7"),
                   Action("WARN_CUSTOMER", "auto", "R7")]
    if pattern == "undocumented" and evidence.coordinated_abuse:
        actions += [Action("CREATE_CASE", "auto", "R9"),
                    Action("FILE_REPORT", "L2", "R9"),
                    Action("ESCALATE_TO_ANALYST", "auto", "R9")]
    if evidence.verdict_uncertain and evidence.exposure_usd > 500:
        actions.append(Action("ESCALATE_TO_ANALYST", "auto", "R8"))
    return dedupe(actions)

def route_for_exposure(exposure_usd: float) -> str:
    return "L1" if exposure_usd <= 2500 else "L2"

def sar_decision(verdict, pattern, exposure_usd, shared_origin) -> tuple[bool, str]:
    if verdict != "fraud":
        return False, "No confirmed/strongly suspected fraud — no filing required (Sec 3a)."
    if exposure_usd > 1000 or shared_origin or pattern == "undocumented":
        return True, "Sec 3a: exposure > $1,000 or shared-origin/undocumented coordinated activity."
    return False, "Confirmed fraud but below filing thresholds and no shared-origin link (Sec 3a)."
```

`tests/test_policy_engine.py` includes one dedicated test per rule R1–R10, each constructing a minimal `EvidenceBundle` fixture that should trigger exactly that rule and asserting the exact action list and route. This is the single most defensible artifact in the submission — a judge can run `pytest` and see the policy is mechanically correct.

---

## 7. Handling Simulated Evidence Responses

Stored in Supabase, not a flat file, so the frontend can display and edit assumptions per case:

```sql
create table simulated_responses (
  case_id text primary key,
  response_type text check (response_type in ('customer_validation','step_up_auth','analyst_info')),
  assumed_response text not null,
  rationale text
);
```
One row is authored per case where the agent is expected to request evidence, e.g. `HHG-017 | customer_validation | "Customer states they did not make these purchases and still has the card" | matches card_testing pattern with high confidence`. The LangGraph `REQUEST_EVIDENCE` node reads this table via the Supabase Python client and logs it verbatim into `evidence_requests[].assumed_response`.

---

## 8. Answer File Compliance

`schema/answer_schema.py` — a Pydantic model transcribing the entire Answer Format section field-for-field: top level (`case_id`, `case`, `evidence_requests`, `next_best_actions`, `sar`, `stop_reason`, `tool_calls`, `tokens`, `latency_s`); the nested `case` object with all 15 fields; the `sar` object with all 6 fields; `next_best_actions` with `initial`/`final`/`what_changed`. Every `EMIT_ANSWER_FILE` node call runs `AnswerFile.model_validate(state)` before writing to disk — a validation failure blocks the case from being marked complete and surfaces in the dashboard as a red status, rather than silently producing a malformed file.

`scripts/validate_all_cases.py` runs post-batch:
- Confirms 20 files exist, named exactly `<case_id>.json`, in `cases/`.
- Confirms every referenced ID (`affected_txn_ids`, `connected_card_ids`, `similar_prior_cases`, etc.) exists in the loaded dataset by querying TigerGraph — catching the disqualifying "invented ID" failure mode before submission.
- Confirms `sar.file` agrees with whether `FILE_REPORT` appears in `next_best_actions.final`.
- Confirms `pattern_description` is non-empty exactly when `pattern == "undocumented"`, empty otherwise.
- Confirms `legitimate` verdicts have empty `affected_txn_ids`, zero `exposure_usd`, and `sar.file == false`.

---

## 9. TypeScript Frontend (Next.js, deployed on Vercel)

### Structure
```
frontend/
  app/
    layout.tsx
    page.tsx                     // Case Feed: table of all 20 cases, verdict/status/exposure/route badges
    cases/[caseId]/page.tsx      // Investigation Trace: step-by-step LangGraph node outputs
    graph/[caseId]/page.tsx      // Graph View: force-directed render of the card/device/region neighborhood
  components/
    CaseTable.tsx
    EvidenceTimeline.tsx
    ActionBadge.tsx              // color-coded auto/L1/L2 route chips
    PolicyRuleTag.tsx            // hoverable citation chip linking to the exact rule text
    GraphCanvas.tsx              // react-force-graph wrapper
  lib/
    supabaseClient.ts            // anon-key client, read-only
    api.ts                       // typed fetch wrappers to the FastAPI backend
  types/
    answerFile.ts                // TS types mirroring answer_schema.py field-for-field
```

### Key screens
- **Case Feed** — pulls from the Supabase `cases` table (mirrored from TigerGraph on write) for fast list rendering: `case_id`, `verdict`, `status`, `fraud_probability`, `exposure_usd`, `pattern`, final action route badges.
- **Investigation Trace** — calls `GET /api/cases/{caseId}/trace` on the backend, which returns the full LangGraph node-by-node output (evidence gathered, retrieval hits, policy rule firing, initial vs. final actions, `what_changed`). This is the page recorded for the demo video since it visibly proves the investigation flow end to end.
- **Graph View** — calls `GET /api/cases/{caseId}/neighborhood`; the backend queries TigerGraph for the card/device/region subgraph and returns nodes/edges as JSON for `react-force-graph` to render.

### package.json essentials
```json
{
  "dependencies": {
    "next": "^14.2.0",
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "@supabase/supabase-js": "^2.45.0",
    "react-force-graph-2d": "^1.25.0",
    "typescript": "^5.5.0"
  }
}
```

---

## 10. Backend API (FastAPI, deployed on Render)

```
backend/
  main.py                    # FastAPI app, CORS configured for the Vercel domain
  agent/
    graph.py                 # LangGraph state machine definition
    policy_engine.py
    tools_mcp.py              # TigerGraph MCP client wrappers
    groq_client.py            # thin wrapper around Groq's OpenAI-compatible chat completions
  etl/                        # one-time load scripts (Section 4)
  schema/
    answer_schema.py
  tests/
    test_policy_engine.py
  routes/
    cases.py                  # GET /api/cases, GET /api/cases/{id}, GET /api/cases/{id}/trace,
                               # GET /api/cases/{id}/neighborhood, POST /api/cases/{id}/run
  requirements.txt
```

### Key endpoints
| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/cases` | List all 20 case summaries (proxies/reads Supabase) |
| `GET` | `/api/cases/{case_id}` | Full answer-file JSON for one case |
| `GET` | `/api/cases/{case_id}/trace` | Full LangGraph execution trace for the Investigation Trace UI |
| `GET` | `/api/cases/{case_id}/neighborhood` | Graph nodes/edges for the Graph View UI |
| `POST` | `/api/cases/{case_id}/run` | Re-run the agent for one case on demand (used for the live demo) |
| `GET` | `/api/health` | Render health-check endpoint |

### requirements.txt essentials
```
fastapi
uvicorn[standard]
langgraph
langchain-core
pyTigerGraph
groq
supabase
pydantic>=2
sentence-transformers
pandas
```

---

## 11. Deployment Instructions

### 11.1 TigerGraph
1. Provision TigerGraph Community Edition (Docker), reachable from the Render backend, **or** create a TigerGraph Savanna workspace at https://savanna.tgcloud.io and note its REST++ endpoint, GraphQL endpoint, username, and password.
2. If using Savanna, enable auto-stop/auto-start in workspace settings to conserve free-tier hours.
3. Run `schema/create_schema.gsql` against the instance, then run every ETL script from Section 4 in order.
4. Record the connection details as environment variables (below) — never commit credentials to the repo.

### 11.2 Supabase
1. Create a new Supabase project at https://supabase.com.
2. In the SQL editor, run the schema for `cases`, `case_pack`, `simulated_responses`, and an `audit_log` table:
   ```sql
   create table cases (
     case_id text primary key,
     status text, verdict text, fraud_probability numeric,
     pattern text, exposure_usd numeric, summary text,
     payload jsonb not null,           -- full answer-file JSON
     updated_at timestamptz default now()
   );
   create table case_pack (
     case_id text primary key, opened_at timestamptz, trigger_type text,
     trigger_text text, flagged_txn_id text, card_id text, customer_id text, risk_score numeric
   );
   create table audit_log (
     id bigserial primary key, case_id text, node_name text, payload jsonb, created_at timestamptz default now()
   );
   ```
3. Enable Row Level Security; add a read-only policy for the `anon` key on `cases` and `case_pack` (frontend reads), restrict writes to the `service_role` key (backend only).
4. Copy the project URL, `anon` public key, and `service_role` secret key.

### 11.3 Groq
1. Create a free account at https://console.groq.com.
2. Generate an API key from the console.
3. Confirm free-tier rate limits are sufficient for a 20-case batch run (they comfortably are for this workload); implement simple exponential backoff/retry in the LangGraph loop in case of throttling mid-run.

### 11.4 Backend on Render
1. Push the `backend/` directory to GitHub.
2. In Render, create a new **Web Service**, connect the repo, set root directory to `backend/`.
3. Build command: `pip install -r requirements.txt`. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`.
4. Set environment variables in Render's dashboard:
   ```
   TIGERGRAPH_HOST=...
   TIGERGRAPH_USERNAME=...
   TIGERGRAPH_PASSWORD=...
   TIGERGRAPH_GRAPH_NAME=FraudInvestigation
   GROQ_API_KEY=...
   SUPABASE_URL=...
   SUPABASE_SERVICE_ROLE_KEY=...
   ALLOWED_ORIGINS=https://<your-vercel-app>.vercel.app
   ```
5. Deploy. Confirm `GET /api/health` returns 200 before wiring the frontend.
6. Run the ETL scripts once against the deployed TigerGraph instance before generating any case answers.

### 11.5 Frontend on Vercel
1. Push the `frontend/` directory to GitHub (same repo, different root, or a separate repo — either works).
2. In Vercel, import the project, set root directory to `frontend/`.
3. Framework preset: Next.js (auto-detected).
4. Set environment variables:
   ```
   NEXT_PUBLIC_SUPABASE_URL=...
   NEXT_PUBLIC_SUPABASE_ANON_KEY=...
   NEXT_PUBLIC_API_BASE_URL=https://<your-render-service>.onrender.com
   ```
5. Deploy. Confirm the Case Feed page loads data from Supabase and the Investigation Trace page successfully calls the Render backend (verify CORS correctly allows the Vercel domain).
6. Optional: set up automatic deploys on push to `main` for both Vercel and Render.

---

## 12. Full Requirements Traceability (Hackathon README/PDF)

| Requirement | Where addressed |
|---|---|
| TigerGraph for graph + vector storage | Sections 3, 4, 6 |
| GSQL + graph algorithms | Sections 5, 4 (NEXT-chain job) |
| TigerGraph MCP | Sections 5, 10 |
| GraphRAG (context, not raw data) | Section 4 step 6, Section 6 ASSESS/SAR_WRITE nodes |
| User interface showing investigation/case/evidence/uncertainty/recommendations/actions | Section 9 |
| Case created/progressed, written to graph | Section 6 WRITE_CASE_TO_GRAPH, Section 3 `Case` vertex |
| Case memory retrieval from prior cases | Section 6 RETRIEVE_MEMORY, Section 3 `CITES` edge |
| Controlled evidence-gathering actions | Section 6 REQUEST_EVIDENCE, Section 7 |
| Next best action, initial vs. final, changeable | Section 6 DECIDE_ACTIONS_INITIAL/FINAL, PolicyEngine |
| Policies, permissions, approval routing | Section 6 PolicyEngine `route_for_exposure` |
| Stopping condition | Section 6 STOP_CHECK |
| Explainability | Section 6 (rule citations), `evidence[].ref` |
| Answer file format (case + SAR + next best action) | Section 8 |
| 20 cases from case pack | Section 4 step 7, Section 8 |

---

## 13. Submission Checklist

- [ ] `cases/HHG-001.json` … `HHG-020.json` — Pydantic-validated, ID-existence-validated
- [ ] Every case written to TigerGraph (`written_to_graph=true`, real `graph_case_id`) and mirrored to Supabase
- [ ] `tests/test_policy_engine.py` passing — one test per R1–R10
- [ ] GitHub repo containing: GSQL schema/algorithm scripts, ETL scripts, LangGraph agent, FastAPI backend, Next.js frontend
- [ ] Frontend live on Vercel, backend live on Render, both pointed at the same TigerGraph + Supabase instances
- [ ] 3–5 minute demo video walking through Case Feed → Investigation Trace → Graph View for at least one fraud case and one legitimate case
- [ ] Technical blog post: what was built, architecture (with the state-machine diagram), how TigerGraph was used, agentic capabilities implemented, what was learned, what would be improved with more time
- [ ] Social post on X/LinkedIn tagging @TigerGraphDB, linking blog/demo
- [ ] Final `scripts/validate_all_cases.py` run clean with zero violations before submission

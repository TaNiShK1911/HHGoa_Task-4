<div align="center">
  <h1>🐯 TigerGraph Agentic Fraud Investigation (HHGoa)</h1>
  <p>An Explainable-First, Graph-Powered Agentic Fraud Investigation System built for the <strong>TigerGraph HHGoa Hackathon</strong>.</p>
</div>

---

## 🏆 Project Overview

This repository contains a full-stack, agentic fraud investigation system that mechanically applies a strict 10-rule Fraud Policy using a **Deterministic Policy Engine** guided by a **LangGraph State Machine**.

Unlike naive LLM wrappers that hallucinate fraud patterns or guess actions, this architecture treats the LLM strictly as an **evidence synthesizer** and **writer** (generating the SAR narrative), while the graph traversal (TigerGraph) handles the hard logic of fetching evidence, and the Python Policy Engine determines the *Next Best Action* mathematically. 

### Key Features
- **Explainable-First Architecture**: Every action taken by the agent (e.g., `BLOCK_CARD`, `FILE_REPORT`) carries a deterministic rule citation (e.g., `R1`, `R5`) traced back to code.
- **TigerGraph MCP Integration**: Dual-mode graph access — routes queries through the [TigerGraph MCP server](https://github.com/tigergraph/tigergraph-mcp) when available, with transparent fallback to direct pyTigerGraph REST calls for resilience.
- **GraphRAG Grounding**: The SAR Narrative and Policy Assessment are grounded purely in semantic chunks stored natively in TigerGraph's vector index (ClosedCase analyst_notes, PolicyChunks, RegDocs).
- **Vite + TanStack Start Dashboard**: A sleek, reactive frontend UI displaying Case Feeds, Investigation Traces (LangGraph logs), and a Force-Directed Graph View of the transaction neighborhood.

---

## 🏗️ Architecture Stack

| Layer | Technology | Justification |
|-------|------------|---------------|
| **Graph & Vector Database** | TigerGraph Community Edition | Powers fast neighborhood traversal (GSQL), deep link analysis, and embedded GraphRAG vector search. |
| **Agent Orchestration** | LangGraph (Python) | Models the complex 8-step investigation loop into an inspectable, stateful graph. |
| **Tool Execution** | TigerGraph MCP + pyTigerGraph REST | Dual-mode: queries route through [TigerGraph MCP server](https://github.com/tigergraph/tigergraph-mcp) when available (set `TIGERGRAPH_MCP_URL`), with transparent fallback to direct pyTigerGraph REST. |
| **LLM Provider** | Groq (`llama-3.3-70b-versatile`, `llama-3.1-8b-instant`) | Blazing fast reasoning for evidence synthesis and SAR narrative drafting. |
| **Backend REST API** | FastAPI | Hosts the LangGraph runner and TigerGraph integrations; serves endpoints to the frontend. |
| **Frontend UI** | Vite, TanStack Start, Tailwind CSS | High-performance visualization dashboard. |
| **Metadata Store** | Supabase (PostgreSQL) | Stores agent configuration and read-heavy case metadata for the dashboard. |

---

## 🕸️ Graph Schema

### Vertices
| Vertex | Key attributes | Populated from |
|---|---|---|
| `Customer` | `customer_id` (PK), `first_seen_ts`, `n_cards` | `transactions.csv` |
| `Card` | `card_id` (PK), `customer_id`, `card_network`, `device_cluster_id` | `transactions.csv` |
| `Transaction` | `txn_id` (PK), `ts`, `amount`, `product_cd`, `risk_score` | `transactions.csv` |
| `DeviceProfile` | `device_key` (PK), `device_type`, `is_new_flag_seen` | `identity.csv` |
| `ClosedCase` | `case_id` (PK), `outcome`, `pattern`, `analyst_notes` (embedded text) | `closed_cases_history.csv` |
| `Case` | `case_id` (PK), `status`, `verdict`, `fraud_probability`, `summary` | Written by Agent |
| `PolicyChunk` / `PatternChunk` / `RegDoc` | Text and vector embeddings along with  Internal configurations & Docs |

### Edges
- `Customer -(OWNS)-> Card -(MADE)-> Transaction -(NEXT)-> Transaction`
- `Transaction -(FROM_DEVICE)-> DeviceProfile`
- `ClosedCase -(INVOLVES)-> Transaction` (and `Card`)
- `Case -(AFFECTS)-> Transaction` (and `Card`, `ClosedCase`, `PolicyChunk`)

---

## 📂 Repository Structure

```text
.
├── backend/                  # FastAPI Application & LangGraph Agent
│   ├── agent/                # LangGraph nodes, edges, state schema, & Groq client
│   │   ├── graph.py          # 16-node LangGraph state machine
│   │   ├── groq_client.py    # Groq LLM wrapper (llama-3.3-70b + llama-3.1-8b)
│   │   ├── policy_engine.py  # Deterministic Policy Engine (R1–R10)
│   │   └── tools_mcp.py      # TigerGraph MCP + REST dual-mode tool wrappers
│   ├── etl/                  # One-time bulk data load scripts for TigerGraph
│   ├── routes/               # API Endpoints (/api/cases, /api/cases/{id}/trace, etc.)
│   ├── schema/               # Pydantic schemas + GSQL graph schema
│   ├── scripts/              # Batch runner + answer file validator
│   ├── tests/                # Deterministic Policy Engine unit tests (pytest)
│   ├── main.py               # Application entry point
│   └── requirements.txt      # Python dependencies
│
├── frontend/                 # Vite + TanStack Start Application
│   ├── src/
│   │   ├── routes/           # Case Feed, Investigation Trace, Graph View
│   │   ├── components/       # StatusBadges, RuleChip, GraphCanvas, etc.
│   │   ├── lib/              # API wrappers, Supabase client, policy rules
│   │   └── types/            # TypeScript types mirroring backend Pydantic models
│   ├── package.json          # Node dependencies
│   └── vite.config.ts        # Vite configuration
│
├── cases/                    # 20 generated answer files (HHG-001.json – HHG-020.json)
└── render.yaml               # Render deployment configuration
```

---

## 🚀 Quickstart Guide

### 1. Environment Setup
Create `backend/.env`:
```env
TIGERGRAPH_HOST=https://your-instance.i.tgcloud.io
TIGERGRAPH_USERNAME=tigergraph
TIGERGRAPH_PASSWORD=tigergraph
TIGERGRAPH_GRAPH_NAME=FraudInvestigation
TIGERGRAPH_SECRET=your_restpp_secret
TIGERGRAPH_MCP_URL=http://localhost:9000  # optional — MCP server URL
GROQ_API_KEY=gsk_...
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=ey...
ALLOWED_ORIGINS=http://localhost:3000
```

Create `frontend/.env`:
```env
VITE_SUPABASE_URL=https://your-project.supabase.co
VITE_SUPABASE_ANON_KEY=ey...
VITE_API_BASE_URL=http://localhost:8000
```

### 2. Run the Backend API
```bash
cd backend
python -m venv venv
source venv/bin/activate  # (or venv\Scripts\activate on Windows)
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```
> The backend should now be running at `http://localhost:8000`.

### 3. Run the Frontend UI
```bash
cd frontend
npm install
npm run dev
```
> The dashboard should now be accessible at `http://localhost:3000`.

### 4. Load the Data and Run the Batch

1. **Initialize the Schema**: Run the GSQL script at `backend/schema/create_schema.gsql` in your TigerGraph instance.
2. **Run ETL**: Load the hackathon data:
   ```bash
   cd backend
   python etl/load_transactions.py
   python etl/load_identity.py
   python etl/load_closed_cases.py
   python etl/embed_documents.py
   python etl/load_case_pack.py
   python etl/validate_load.py
   ```
3. **Run Batch Investigation**: Generate the 20 case answer files:
   ```bash
   python scripts/run_batch.py
   ```
4. **Validate Output**: Ensure all 20 `.json` files in `cases/` pass the hackathon schema checks:
   ```bash
   python scripts/validate_all_cases.py
   ```

---

## 🧠 The Agentic Flow (LangGraph)

When a case is triggered, the agent executes a highly deterministic state machine:
1. **TRIGGER**: Loads the case from the case pack CSV.
2. **LOAD_CASE_CONTEXT**: Pulls flagged transaction, card, and customer data.
3. **GATHER_EVIDENCE**: Dispatches parallel GSQL queries (Card Window, Device Neighbors, Region Cluster, Baseline).
4. **RETRIEVE_MEMORY**: Runs vector search over closed cases (GraphRAG) + graph traversal.
5. **ASSESS**: Groq `llama-3.3-70b-versatile` synthesizes the raw graph evidence.
6. **SINGLE_SIGNAL_CHECK**: Groq `llama-3.1-8b-instant` classifies single-signal risk (cheap).
7. **DECIDE_ACTIONS_INITIAL**: Deterministic Policy Engine assigns actions purely by rule.
8. **REQUEST_EVIDENCE** *(conditional)*: Requests simulated customer input if R1 fires.
9. **RE_ASSESS** *(conditional)*: Re-evaluates with new evidence.
10. **DECIDE_ACTIONS_FINAL**: Adjusts actions based on the new evidence.
11. **STOP_CHECK**: Determines stopping condition.
12. **SAR_DECISION**: Deterministic check for SAR filing thresholds.
13. **SAR_WRITE** *(conditional)*: Drafts the FinCEN narrative grounded on RegDoc chunks.
14. **WRITE_CASE_TO_GRAPH**: Saves the full context back to TigerGraph as an InvestigationCase vertex.
15. **EMIT_ANSWER_FILE**: Pydantic-validates and writes the JSON answer file to `cases/`.

### 🛠️ GSQL Query Library (Tools Exposed via MCP)

| Query name | Purpose | Returns |
|---|---|---|
| `card_window(card_id, hours)` | All transactions on a card within a rolling time window, ordered via the `NEXT` chain | List of transactions with amounts/ts/product_cd |
| `device_neighbors(device_key)` | All cards/customers/transactions sharing a device profile, plus any `ClosedCase` touching that device | Shared-device evidence |
| `region_cluster(region_code, window_days)` | Cards billed in a region with no prior history there | Out-of-region evidence |
| `customer_baseline(customer_id)` | Historical spend pattern: typical amount range, typical product codes, typical channel mix | Baseline check for pattern anomalies |
| `closed_case_lookup(entity_ids)` | Graph traversal to `ClosedCase`s touching any of the given card/device/region IDs | Direct-memory hits |
| `vector_search(query_text, chunk_type, k)` | Vector top-k over `PolicyChunk`, `PatternChunk`, `ClosedCase.analyst_notes`, or `RegDoc` | GraphRAG retrieval |

### ⚙️ Deterministic Policy Engine (Core Differentiator)

A real fraud decision must be auditable and reproducible. This design uses a deterministic Python rules engine (`backend/agent/policy_engine.py`) that strictly transcribes the 10-rule Fraud Policy. The LLM does **not** hallucinate actions.
- `decide_initial()`: Evaluates single-signal rules, card-testing patterns, and shared-origin evidence to output `next_best_actions.initial`.
- `decide_final()`: Reads simulated customer replies (e.g. `denied`, `confirmed`) or timeouts to assign `next_best_actions.final`.
- `sar_decision()`: Applies Section 3a rules strictly to determine if a SAR report is required based on exposure and undocumented/coordinated abuse.

---

## 🧪 Testing

The Policy Engine is heavily unit-tested. Every rule (R1–R10) has dedicated test fixtures to ensure the agent cannot hallucinate actions:
```bash
cd backend
pytest tests/test_policy_engine.py -v
```

To validate that all generated case files comply with the hackathon Answer Format:
```bash
python scripts/validate_all_cases.py
```

---

## 🚢 Deployment

The project is configured for deployment on **Render** and **Vercel**:
- **Backend (Render)**: FastAPI on Render Web Service (`render.yaml`). Exposes the LangGraph agent, MCP client, and Groq LLM integration. 
- **Frontend (Vercel)**: Next.js/Vite frontend deployed seamlessly via Vercel. 
- **Database (Supabase & TigerGraph)**: Uses Supabase for metadata and simulated evidence configs, while TigerGraph handles heavy graph traversals.

**Environment variables** must be set in the respective Render and Vercel dashboards (or `.env` for local testing). Ensure `ALLOWED_ORIGINS` in the backend includes the frontend domain for proper CORS integration.

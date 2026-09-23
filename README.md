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
- **Direct Graph Execution**: LangGraph connects natively to TigerGraph using direct REST calls via pyTigerGraph, executing GSQL queries dynamically as LangChain tools (bypassing the standard MCP wrapper for speed and reliability).
- **GraphRAG Grounding**: The SAR Narrative and Policy Assessment are grounded purely in semantic chunks stored natively in TigerGraph's vector index.
- **Vite + TanStack Start Dashboard**: A sleek, reactive frontend UI displaying Case Feeds, Investigation Traces (LangGraph logs), and a Force-Directed Graph View of the transaction neighborhood.

---

## 🏗️ Architecture Stack

| Layer | Technology | Justification |
|-------|------------|---------------|
| **Graph & Vector Database** | TigerGraph Community Edition | Powers fast neighborhood traversal (GSQL), deep link analysis, and embedded GraphRAG vector search. |
| **Agent Orchestration** | LangGraph (Python) | Models the complex 8-step investigation loop into an inspectable, stateful graph. |
| **Tool Execution** | Direct REST API (pyTigerGraph) | Instead of the standard MCP server, we bypassed it for direct pyTigerGraph REST calls to optimize performance and reliability within the tight hackathon deadline, executing GSQL queries dynamically as LangChain tools. |
| **LLM Provider** | Groq (`llama-3.3-70b-versatile`) | Blazing fast reasoning for evidence synthesis and complex SAR narrative drafting. |
| **Backend REST API** | FastAPI | Hosts the LangGraph runner and TigerGraph integrations; serves endpoints to the frontend. |
| **Frontend UI** | Vite, TanStack Start, Tailwind CSS | High-performance visualization dashboard. |
| **Metadata Store** | Supabase (PostgreSQL) | Stores agent configuration and read-heavy case metadata for the dashboard. |

---

## 📂 Repository Structure

```text
.
├── backend/                  # FastAPI Application & LangGraph Agent
│   ├── agent/                # LangGraph nodes, edges, state schema, & Groq client
│   ├── etl/                  # One-time bulk data load scripts for TigerGraph
│   ├── routes/               # API Endpoints (/api/cases, /api/cases/{id}/trace, etc.)
│   ├── schema/               # Pydantic schemas (e.g. answer_schema.py) and GSQL schemas
│   ├── tests/                # Deterministic Policy Engine unit tests (PyTest)
│   ├── main.py               # Application entry point
│   └── requirements.txt      # Python dependencies
│
├── frontend/                 # Vite + TanStack Start Application
│   ├── src/                  # Source files (Case Feed, Trace, Graph View)
│   ├── components/           # UI Components (CaseTable, GraphCanvas, etc.)
│   ├── lib/                  # Supabase client and API wrappers
│   ├── types/                # TypeScript types mirroring backend Pydantic models
│   ├── package.json          # Node dependencies
│   └── vite.config.ts        # Vite configuration
```

---

## 🚀 Quickstart Guide

To run the full stack locally, you need a running **TigerGraph** instance (CE or Savanna) and a **Supabase** project.

### 1. Environment Setup
Configure your environment variables. 
Create `backend/.env`:
```env
TIGERGRAPH_HOST=https://your-instance.i.tgcloud.io
TIGERGRAPH_USERNAME=tigergraph
TIGERGRAPH_PASSWORD=tigergraph
TIGERGRAPH_GRAPH_NAME=FraudInvestigation
TIGERGRAPH_SECRET=your_restpp_secret
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
bun install  # or npm install
bun run dev  # or npm run dev
```
> The dashboard should now be accessible at `http://localhost:8080`.

### 4. Load the Data and Run the Batch

Before you can run the investigation agent, you must initialize the TigerGraph schema and load the hackathon dataset.

1. **Initialize the Schema**: Run the GSQL script located at `backend/schema/create_schema.gsql` in your TigerGraph instance.
2. **Run ETL**: Load the data using the provided ETL scripts:
   ```bash
   cd backend
   python etl/load_transactions.py
   python etl/load_identity.py
   ```
3. **Run Batch Investigation**: Generate the 20 case results as required by the hackathon submission format:
   ```bash
   python scripts/run_batch.py
   ```
4. **Validate Output**: Ensure the 20 `.json` files in `backend/cases/` perfectly match the hackathon schema requirements:
   ```bash
   python scripts/validate_all_cases.py
   ```

---

## 🧠 The Agentic Flow (LangGraph)

When a case is triggered, the agent executes a highly deterministic state machine:
1. **LOAD_CASE_CONTEXT**: Pulls flagged transaction, card, and customer baselines.
2. **GATHER_EVIDENCE**: Dispatches parallel GSQL queries (Card Window, Device Neighbors, Region Cluster, Baseline).
3. **RETRIEVE_MEMORY**: Runs a vector-search over historical closed cases (GraphRAG).
4. **ASSESS**: Groq synthesizes the raw graph evidence.
5. **DECIDE_ACTIONS_INITIAL**: Python Deterministic Policy Engine assigns actions (e.g. `BLOCK_CARD`) purely by rule.
6. **REQUEST_EVIDENCE**: Requests simulated customer input if R1 fires.
7. **DECIDE_ACTIONS_FINAL**: Adjusts actions based on the new evidence.
8. **SAR_WRITE**: Drafts the FinCEN report if thresholds are breached.
9. **WRITE_CASE_TO_GRAPH**: Saves the full context back to TigerGraph.

---

## 🧪 Testing

The Policy Engine is heavily unit-tested. Every rule (R1-R10) has a dedicated fixture to ensure the agent cannot hallucinate actions.
```bash
cd backend
pytest tests/test_policy_engine.py
```

To validate that all generated case files comply strictly with the hackathon Answer Format:
```bash
python backend/scripts/validate_all_cases.py
```

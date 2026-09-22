"""
FastAPI Application — Backend entry point.

Section 10 of the implementation plan.

Hosts:
  - LangGraph agent
  - TigerGraph MCP client
  - Groq calls
  - Supabase client
  - REST endpoints for the frontend

CORS configured to allow only the deployed Vercel frontend origin.
"""

from __future__ import annotations

import os
import logging
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── App initialization ───────────────────────────────────────────────────────

app = FastAPI(
    title="TigerGraph Fraud Investigation API",
    description="Agentic fraud investigation backend powered by TigerGraph, LangGraph, and Groq",
    version="1.0.0",
)

# ── CORS ─────────────────────────────────────────────────────────────────────

allowed_origins_str = os.environ.get("ALLOWED_ORIGINS", "")
allowed_origins = [
    origin.strip()
    for origin in allowed_origins_str.split(",")
    if origin.strip()
]

# Always allow localhost for development
allowed_origins.extend([
    "http://localhost:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3000",
])

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Shared clients (lazy-initialized singletons) ────────────────────────────

_tg_tools = None
_groq_client = None
_supabase_client = None


def get_tg_tools():
    """Get or create TigerGraph tools singleton."""
    global _tg_tools
    if _tg_tools is None:
        from agent.tools_mcp import TigerGraphTools
        _tg_tools = TigerGraphTools()
    return _tg_tools


def get_groq_client():
    """Get or create Groq client singleton."""
    global _groq_client
    if _groq_client is None:
        from agent.groq_client import GroqClient
        _groq_client = GroqClient()
    return _groq_client


def get_supabase_client():
    """Get or create Supabase client singleton."""
    global _supabase_client
    if _supabase_client is None:
        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
        if url and key:
            try:
                from supabase import create_client
                _supabase_client = create_client(url, key)
                logger.info("Supabase client initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize Supabase client: {e}")
        else:
            logger.warning("Supabase credentials not set. Running without Supabase.")
    return _supabase_client


# ── Include routes ───────────────────────────────────────────────────────────

from routes.cases import router as cases_router
app.include_router(cases_router)


# ── Startup ──────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup_event():
    """Log startup configuration."""
    logger.info("=" * 60)
    logger.info("TigerGraph Fraud Investigation API starting up")
    logger.info("=" * 60)
    logger.info(f"CORS allowed origins: {allowed_origins}")
    logger.info(f"TigerGraph host: {os.environ.get('TIGERGRAPH_HOST', 'NOT SET')}")
    logger.info(f"Groq API key: {'SET' if os.environ.get('GROQ_API_KEY') else 'NOT SET'}")
    logger.info(f"Supabase URL: {'SET' if os.environ.get('SUPABASE_URL') else 'NOT SET'}")
    logger.info("=" * 60)

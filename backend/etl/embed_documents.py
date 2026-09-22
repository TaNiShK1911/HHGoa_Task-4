"""
ETL: Embed documents and create vector indices — Section 4, Step 6.

Chunks and embeds:
  1. Fraud Policy (R0–R10) → PolicyChunk vertices
  2. Five known fraud patterns → PatternChunk vertices
  3. ClosedCase.analyst_notes → embedding attribute on existing vertices
  4. FinCEN SAR Narrative Guidance → RegDoc vertices

Embeddings computed locally with sentence-transformers/all-MiniLM-L6-v2
(384-dimensional, no API cost).
"""

from __future__ import annotations

import os
import sys
import logging
from typing import List, Tuple

import pyTigerGraph as tg
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_connection() -> tg.TigerGraphConnection:
    conn = tg.TigerGraphConnection(
        host=os.environ["TIGERGRAPH_HOST"],
        username=os.environ.get("TIGERGRAPH_USERNAME", "tigergraph"),
        password=os.environ["TIGERGRAPH_PASSWORD"],
        graphname=os.environ.get("TIGERGRAPH_GRAPH_NAME", "FraudInvestigation"),
    )
    try:
        secret = os.environ.get("TIGERGRAPH_SECRET")
        if secret:
            conn.getToken(secret)
        else:
            conn.getToken(conn.createSecret())
    except Exception:
        logger.warning("Could not create secret/token.")
    return conn


def get_embedder():
    """Load the sentence-transformers model for local embedding."""
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    logger.info(f"Loaded embedding model: all-MiniLM-L6-v2 (dim={model.get_sentence_embedding_dimension()})")
    return model


# ── Policy rules: one chunk per rule R0–R10 ──────────────────────────────────

POLICY_CHUNKS: List[Tuple[str, str]] = [
    ("R0", "Section 0: What the agent starts with. Every transaction carries a risk_score between 0 and 1 from the bank's detection model. The model is useful and imperfect: many high scores are legitimate, and some fraud scores low. A score is a reason to look, never a verdict. The only confirmed outcomes are in the closed cases."),
    ("R1", "R1: Verify before you block on a weak signal. If the case rests on a single signal (including a risk score alone) and your assessed fraud probability is below 0.70, recommend VERIFY_WITH_CUSTOMER or STEP_UP_AUTH before any block. Blocking a legitimate customer on one signal is a policy breach."),
    ("R2", "R2: Customer denies the transaction. Recommend BLOCK_CARD and CREATE_CASE. Add FILE_REPORT if exposure exceeds $1,000 or the case connects to a shared device profile or another card's fraud."),
    ("R3", "R3: Customer confirms the transaction. Recommend CLOSE_NO_FRAUD. Note the confirmation in the case file."),
    ("R4", "R4: No reply within 24 hours. Recommend MONITOR_CARD and DECLINE_TRANSACTION for pending authorizations. Escalate if exposure exceeds $500."),
    ("R5", "R5: Card testing. Three or more small online authorizations on one card within an hour, followed by a larger purchase: recommend DECLINE_TRANSACTION and STEP_UP_AUTH. If a purchase over $100 has already cleared, recommend BLOCK_CARD."),
    ("R6", "R6: Shared origin. When several cards show fraud from the same device profile, the same billing region, or the same recipient email in one window, name the shared element, recommend CREATE_CASE and FILE_REPORT, and MONITOR_CONNECTED_CARDS for every card that shares it."),
    ("R7", "R7: Disputed but legitimate. When the customer disputes a charge that matches their own recurring pattern (same merchant, same amount, monthly), recommend CREATE_CASE, VERIFY_WITH_CUSTOMER, and WARN_CUSTOMER. Do not block."),
    ("R8", "R8: Escalate when uncertain and exposed. If the verdict is uncertain and exposure exceeds $500, or the evidence conflicts, recommend ESCALATE_TO_ANALYST."),
    ("R9", "R9: Undocumented patterns. When activity fits none of the known patterns but the evidence shows coordinated or repeated abuse across customers, recommend CREATE_CASE, FILE_REPORT, and ESCALATE_TO_ANALYST, and describe the pattern in your own words. Do not force it into a known category."),
    ("R10", "R10: Never BLOCK_ALL_CARDS unless at least two of the customer's cards show confirmed fraud or the customer's credentials are confirmed compromised."),
]


# ── Pattern definitions ──────────────────────────────────────────────────────

PATTERN_CHUNKS: List[Tuple[str, str]] = [
    ("card_testing", "Card testing: A stolen card number is checked before use — three or more tiny online authorizations, often under $5, then a larger purchase. Confirmed by the sequence itself. Policy R5."),
    ("card_not_present_fraud", "Card-not-present fraud: The number is used online without the card. Amounts and products that don't fit the cardholder's history, often in a burst of two to four within 48 hours. On its own, one unusual online purchase is ambiguous: verify. Policy R1 to R4."),
    ("card_not_present_new_device", "Card-not-present fraud from a new device: Same as card-not-present fraud, with the identity record marking the device as New for this account, sometimes behind a proxy. Stronger than pattern 2, still not proof: people buy new phones."),
    ("out_of_region_use", "Out-of-region use: Card-present purchases in a billing region the cardholder has no history in, while their normal activity continues at home. Several days of purchases in one new region is a trip, not a clone. Policy R2, R3."),
    ("account_takeover", "Account takeover: Mixed-channel activity inconsistent with the cardholder, often with device and match-flag anomalies, pointing to stolen credentials rather than a stolen number."),
]


# ── FinCEN regulatory document chunks ────────────────────────────────────────

REGDOC_CHUNKS: List[Tuple[str, str, str]] = [
    ("FINCEN-SAR-NARRATIVE-001",
     "https://www.fincen.gov/system/files/shared/sar_guidance_narrative.pdf",
     "FinCEN SAR Narrative Guidance: A complete and sufficient SAR narrative should include the following information: a clear, complete and chronological description of the activity; identification of the subjects involved; identification of any accounts, financial institutions, or other entities involved; a description of the suspicious activity; a statement of the reason for filing the SAR; and any other pertinent information."),
    ("FINCEN-SAR-NARRATIVE-002",
     "https://www.fincen.gov/system/files/shared/sar_guidance_narrative.pdf",
     "The narrative should answer the questions: Who is conducting the suspicious activity? What instruments or mechanisms are being used? When did the suspicious activity occur? Where did the suspicious activity take place? Why is the activity suspicious? How was the suspicious activity conducted?"),
    ("FINCEN-SAR-NARRATIVE-003",
     "https://www.fincen.gov/system/files/shared/sarnarrcompletguidfinal_112003.pdf",
     "The SAR narrative is the single most important element of the SAR filing. Well-written narratives are essential to support effective law enforcement investigations and regulatory actions. A poorly written narrative may render the entire filing ineffective."),
    ("FINCEN-ATO-ADVISORY-001",
     "https://www.fincen.gov/resources/advisories/fincen-advisory-fin-2011-a016",
     "Account takeover fraud involves unauthorized access to a customer's accounts by a third party. Red flags include: new device or IP address for an established account, changes to account contact information followed by transactions, rapid series of transactions inconsistent with account history, and failed authentication attempts."),
    ("FINCEN-FILING-001",
     "https://www.fincen.gov/system/files/2025-10/SAR-FAQs-October-2025.pdf",
     "Filing obligations: A financial institution must file a SAR when it knows, suspects, or has reason to suspect that a transaction involves funds from illegal activity, is designed to evade BSA reporting requirements, or has no business or apparent lawful purpose. The aggregate amount of suspicious transactions determines filing thresholds."),
]


def embed_documents():
    """Create embeddings for policy chunks, pattern chunks, and regulatory docs."""
    conn = get_connection()
    model = get_embedder()

    logger.info("=" * 60)
    logger.info("STEP 1: Embedding Policy Chunks (R0–R10)")
    logger.info("=" * 60)

    for rule_id, text in POLICY_CHUNKS:
        embedding = model.encode(text).tolist()
        try:
            conn.upsertVertex("PolicyChunk", rule_id, attributes={
                "text": text,
                "embedding": embedding,
            })
            logger.info(f"  ✓ {rule_id}")
        except Exception as e:
            logger.error(f"  ✗ {rule_id}: {e}")

    logger.info("=" * 60)
    logger.info("STEP 2: Embedding Pattern Chunks")
    logger.info("=" * 60)

    for pattern_id, text in PATTERN_CHUNKS:
        embedding = model.encode(text).tolist()
        try:
            conn.upsertVertex("PatternChunk", pattern_id, attributes={
                "text": text,
                "embedding": embedding,
            })
            logger.info(f"  ✓ {pattern_id}")
        except Exception as e:
            logger.error(f"  ✗ {pattern_id}: {e}")

    logger.info("=" * 60)
    logger.info("STEP 3: Embedding Regulatory Document Chunks")
    logger.info("=" * 60)

    for doc_id, source_url, chunk_text in REGDOC_CHUNKS:
        embedding = model.encode(chunk_text).tolist()
        try:
            conn.upsertVertex("RegDoc", doc_id, attributes={
                "source_url": source_url,
                "chunk_text": chunk_text,
                "embedding": embedding,
            })
            logger.info(f"  ✓ {doc_id}")
        except Exception as e:
            logger.error(f"  ✗ {doc_id}: {e}")

    logger.info("=" * 60)
    logger.info("STEP 4: Embedding ClosedCase analyst_notes")
    logger.info("=" * 60)

    # Fetch all ClosedCase vertices and embed their analyst_notes
    try:
        cases = conn.getVertices("ClosedCase", limit=10000)
        if cases:
            logger.info(f"  Found {len(cases)} closed cases to embed")
            batch_notes = []
            batch_ids = []

            for case in cases:
                attrs = case.get("attributes", case)
                notes = attrs.get("analyst_notes", "")
                case_id = case.get("v_id", attrs.get("case_id", ""))
                if notes and case_id:
                    batch_notes.append(notes)
                    batch_ids.append(case_id)

            if batch_notes:
                # Batch embed for efficiency
                logger.info(f"  Embedding {len(batch_notes)} analyst notes...")
                embeddings = model.encode(batch_notes, show_progress_bar=True)

                update_dict = {}
                for case_id, embedding in zip(batch_ids, embeddings):
                    update_dict[case_id] = {"embedding": embedding.tolist()}

                try:
                    conn.upsertVertices("ClosedCase", list(update_dict.items()))
                    logger.info(f"  ✓ Bulk updated {len(batch_notes)} embeddings")
                except Exception as e:
                    logger.error(f"  Failed to bulk update embeddings: {e}")
        else:
            logger.warning("  No ClosedCase vertices found — run load_closed_cases.py first")
    except Exception as e:
        logger.error(f"  Failed to embed closed case notes: {e}")

    logger.info("=" * 60)
    logger.info("Embedding complete!")
    logger.info("=" * 60)


if __name__ == "__main__":
    embed_documents()

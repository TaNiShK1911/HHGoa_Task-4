"""
TigerGraph MCP Tool Wrappers — Section 5 of the implementation plan.

Wraps GSQL queries as LangGraph tools via pyTigerGraph. Each tool's return
value maps directly onto the Answer Format's evidence object shape:
    {claim, source, ref, entity_ids}

The mapping happens inside each tool wrapper — not scattered across the
agent graph.

If TigerGraph MCP server is available, uses it; otherwise falls back to
direct REST API calls via pyTigerGraph.
"""

from __future__ import annotations

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pyTigerGraph as tg

logger = logging.getLogger(__name__)


class TigerGraphTools:
    """
    Tool wrappers for TigerGraph GSQL queries.

    Each method returns evidence objects in the Answer Format shape:
        {"claim": str, "source": "graph", "ref": str, "entity_ids": [str]}
    """

    def __init__(
        self,
        host: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        graph_name: Optional[str] = None,
    ):
        self._host = host or os.environ.get("TIGERGRAPH_HOST", "")
        self._username = username or os.environ.get("TIGERGRAPH_USERNAME", "tigergraph")
        self._password = password or os.environ.get("TIGERGRAPH_PASSWORD", "")
        self._graph_name = graph_name or os.environ.get("TIGERGRAPH_GRAPH_NAME", "FraudInvestigation")
        self._conn: Optional[tg.TigerGraphConnection] = None
        self._tool_call_count = 0

    @property
    def tool_call_count(self) -> int:
        return self._tool_call_count

    def reset_tool_call_count(self) -> None:
        self._tool_call_count = 0

    def _get_conn(self) -> tg.TigerGraphConnection:
        """Lazily initialize the TigerGraph connection."""
        if self._conn is None:
            if not self._host:
                raise RuntimeError(
                    "TIGERGRAPH_HOST not set. Cannot connect to TigerGraph."
                )
            self._conn = tg.TigerGraphConnection(
                host=self._host,
                username=self._username,
                password=self._password,
                graphname=self._graph_name,
            )
            # Get auth token
            try:
                secret = os.environ.get("TIGERGRAPH_SECRET")
                if secret:
                    self._conn.getToken(secret)
                else:
                    self._conn.getToken(self._conn.createSecret())
            except Exception as e:
                logger.warning("Could not create secret/token. Proceeding without token auth.")
        return self._conn

    # ── Tool 1: card_window ──────────────────────────────────────────────────

    def card_window(
        self, card_id: str, hours: int = 24
    ) -> Dict[str, Any]:
        """
        All transactions on a card within a rolling time window,
        ordered via the NEXT chain.

        Returns evidence object with transaction details.
        """
        self._tool_call_count += 1
        conn = self._get_conn()

        try:
            # Query transactions on this card, ordered by timestamp
            result = conn.runInstalledQuery("card_window", params={
                "card_id": card_id,
                "hours": hours,
            })
        except Exception as e:
            logger.warning(f"Installed query 'card_window' failed: {e}. Using REST fallback.")
            result = self._card_window_fallback(card_id, hours)

        txn_ids = []
        txn_details = []
        for txn in result:
            txn_id = txn.get("txn_id", txn.get("v_id", ""))
            txn_ids.append(txn_id)
            txn_details.append({
                "txn_id": txn_id,
                "amount": txn.get("TransactionAmt", txn.get("attributes", {}).get("TransactionAmt", 0)),
                "ts": txn.get("ts", txn.get("attributes", {}).get("ts", "")),
                "product_cd": txn.get("ProductCD", txn.get("attributes", {}).get("ProductCD", "")),
                "channel": txn.get("channel", txn.get("attributes", {}).get("channel", "")),
                "risk_score": txn.get("risk_score", txn.get("attributes", {}).get("risk_score", 0)),
            })

        n_txns = len(txn_ids)
        if n_txns == 0:
            claim = f"No transactions found on card {card_id} in the last {hours} hours"
        else:
            amounts = [t["amount"] for t in txn_details]
            claim = (
                f"{n_txns} transactions on card {card_id} within {hours}-hour window, "
                f"amounts ranging ${min(amounts):.2f} to ${max(amounts):.2f}"
            )

        return {
            "claim": claim,
            "source": "graph",
            "ref": f"query:card_window(card_id={card_id}, hours={hours})",
            "entity_ids": txn_ids,
            "_details": txn_details,  # Internal use, not in answer file
        }

    def _card_window_fallback(self, card_id: str, hours: int) -> list:
        """REST API fallback for card_window query."""
        conn = self._get_conn()
        try:
            # Get all transactions for this card via edge traversal
            edges = conn.getEdges("Card", card_id, "MADE")
            txns = []
            for edge in edges:
                txn_id = edge.get("to_id", "")
                if txn_id:
                    try:
                        vtx = conn.getVerticesById("Transaction", txn_id)
                        if vtx:
                            txns.append(vtx[0] if isinstance(vtx, list) else vtx)
                    except Exception:
                        pass
            return txns
        except Exception as e:
            logger.error(f"Fallback card_window also failed: {e}")
            return []

    # ── Tool 2: device_neighbors ─────────────────────────────────────────────

    def device_neighbors(
        self, device_key: str
    ) -> Dict[str, Any]:
        """
        All cards/customers/transactions sharing a device profile,
        plus any ClosedCase touching that device.

        Returns evidence object with shared-device details.
        """
        self._tool_call_count += 1
        conn = self._get_conn()

        try:
            result = conn.runInstalledQuery("device_neighbors", params={
                "device_key": device_key,
            })
        except Exception as e:
            logger.warning(f"Installed query failed: {e}. Using REST fallback.")
            result = self._device_neighbors_fallback(device_key)

        card_ids = set()
        customer_ids = set()
        txn_ids = []
        closed_case_ids = []
        entity_ids = []

        for item in result:
            if isinstance(item, dict):
                v_type = item.get("v_type", "")
                v_id = item.get("v_id", "")
                if v_type == "Card":
                    card_ids.add(v_id)
                elif v_type == "Customer":
                    customer_ids.add(v_id)
                elif v_type == "Transaction":
                    txn_ids.append(v_id)
                elif v_type == "ClosedCase":
                    closed_case_ids.append(v_id)
                entity_ids.append(v_id)

        n_cards = len(card_ids)
        n_cases = len(closed_case_ids)

        if n_cards <= 1 and n_cases == 0:
            claim = f"Device profile {device_key} is used by only one card, no prior cases"
        else:
            parts = []
            if n_cards > 1:
                parts.append(f"shared across {n_cards} cards ({', '.join(sorted(card_ids))})")
            if n_cases > 0:
                parts.append(f"linked to {n_cases} closed case(s) ({', '.join(closed_case_ids)})")
            claim = f"Device profile {device_key}: " + "; ".join(parts)

        return {
            "claim": claim,
            "source": "graph",
            "ref": f"query:device_neighbors(device_key={device_key})",
            "entity_ids": entity_ids,
            "_card_ids": list(card_ids),
            "_closed_case_ids": closed_case_ids,
        }

    def _device_neighbors_fallback(self, device_key: str) -> list:
        """REST fallback for device_neighbors."""
        conn = self._get_conn()
        try:
            edges = conn.getEdges("DeviceProfile", device_key, "DEVICE_USED_IN")
            results = []
            for edge in edges:
                txn_id = edge.get("to_id", "")
                results.append({"v_type": "Transaction", "v_id": txn_id})
            return results
        except Exception as e:
            logger.error(f"Device neighbors fallback failed: {e}")
            return []

    # ── Tool 3: region_cluster ───────────────────────────────────────────────

    def region_cluster(
        self, region_code: str, window_days: int = 30
    ) -> Dict[str, Any]:
        """
        Cards billed in a region with no prior history there,
        and any concurrent activity elsewhere for the same customer.
        """
        self._tool_call_count += 1
        conn = self._get_conn()

        try:
            result = conn.runInstalledQuery("region_cluster", params={
                "region_code": region_code,
                "window_days": window_days,
            })
        except Exception as e:
            logger.warning(f"Installed query failed: {e}. Using REST fallback.")
            result = []

        entity_ids = []
        anomalous_cards = []

        for item in result:
            if isinstance(item, dict):
                v_id = item.get("v_id", item.get("card_id", ""))
                if v_id:
                    entity_ids.append(v_id)
                    anomalous_cards.append(v_id)

        if not anomalous_cards:
            claim = f"No unusual billing region activity found in region {region_code}"
        else:
            claim = (
                f"{len(anomalous_cards)} card(s) billed in region {region_code} "
                f"with no prior history there within {window_days} days"
            )

        return {
            "claim": claim,
            "source": "graph",
            "ref": f"query:region_cluster(region_code={region_code}, window_days={window_days})",
            "entity_ids": entity_ids,
        }

    # ── Tool 4: customer_baseline ────────────────────────────────────────────

    def customer_baseline(
        self, customer_id: str
    ) -> Dict[str, Any]:
        """
        Historical spend pattern: typical amount range, product codes,
        channel mix. Used for 'does this fit the cardholder's history' check.
        """
        self._tool_call_count += 1
        conn = self._get_conn()

        try:
            result = conn.runInstalledQuery("customer_baseline", params={
                "customer_id": customer_id,
            })
        except Exception as e:
            logger.warning(f"Installed query failed: {e}. Using REST fallback.")
            result = self._customer_baseline_fallback(customer_id)

        baseline = {}
        if result and isinstance(result, list) and len(result) > 0:
            baseline = result[0] if isinstance(result[0], dict) else {}

        avg_amount = baseline.get("avg_amount", 0)
        min_amount = baseline.get("min_amount", 0)
        max_amount = baseline.get("max_amount", 0)
        n_txns = baseline.get("n_txns", 0)
        typical_products = baseline.get("typical_products", [])
        channel_mix = baseline.get("channel_mix", {})

        claim = (
            f"Customer {customer_id} baseline: {n_txns} historical transactions, "
            f"amount range ${min_amount:.2f}–${max_amount:.2f} (avg ${avg_amount:.2f}), "
            f"typical products: {', '.join(typical_products) if typical_products else 'unknown'}"
        )

        return {
            "claim": claim,
            "source": "graph",
            "ref": f"query:customer_baseline(customer_id={customer_id})",
            "entity_ids": [customer_id],
            "_baseline": baseline,
        }

    def _customer_baseline_fallback(self, customer_id: str) -> list:
        """REST fallback for customer_baseline."""
        conn = self._get_conn()
        try:
            # Get all cards for this customer
            edges = conn.getEdges("Customer", customer_id, "OWNS")
            all_amounts = []
            products = set()
            channels = {"online": 0, "in_person": 0}

            for edge in edges:
                card_id = edge.get("to_id", "")
                if card_id:
                    txn_edges = conn.getEdges("Card", card_id, "MADE")
                    for te in txn_edges[:100]:  # Limit for performance
                        txn_id = te.get("to_id", "")
                        try:
                            vtx = conn.getVerticesById("Transaction", txn_id)
                            if vtx:
                                attrs = vtx[0].get("attributes", vtx[0]) if isinstance(vtx, list) else vtx.get("attributes", vtx)
                                amt = attrs.get("TransactionAmt", 0)
                                if amt:
                                    all_amounts.append(float(amt))
                                prod = attrs.get("ProductCD", "")
                                if prod:
                                    products.add(prod)
                                ch = attrs.get("channel", "")
                                if ch in channels:
                                    channels[ch] += 1
                        except Exception:
                            pass

            if all_amounts:
                return [{
                    "avg_amount": sum(all_amounts) / len(all_amounts),
                    "min_amount": min(all_amounts),
                    "max_amount": max(all_amounts),
                    "n_txns": len(all_amounts),
                    "typical_products": list(products),
                    "channel_mix": channels,
                }]
            return [{"avg_amount": 0, "min_amount": 0, "max_amount": 0, "n_txns": 0, "typical_products": [], "channel_mix": {}}]
        except Exception as e:
            logger.error(f"Customer baseline fallback failed: {e}")
            return [{"avg_amount": 0, "min_amount": 0, "max_amount": 0, "n_txns": 0, "typical_products": [], "channel_mix": {}}]

    # ── Tool 5: closed_case_lookup ───────────────────────────────────────────

    def closed_case_lookup(
        self, entity_ids: List[str]
    ) -> Dict[str, Any]:
        """
        Graph traversal to ClosedCases touching any of the given
        card/device/region IDs. Returns direct-memory hits.
        """
        self._tool_call_count += 1
        conn = self._get_conn()

        found_cases = []
        all_entity_ids = []

        for entity_id in entity_ids:
            try:
                # Try looking up as card → HAD_CASE edge
                edges = conn.getEdges("Card", entity_id, "HAD_CASE")
                for edge in edges:
                    case_id = edge.get("to_id", "")
                    if case_id and case_id not in [c["case_id"] for c in found_cases]:
                        try:
                            case_vtx = conn.getVerticesById("ClosedCase", case_id)
                            if case_vtx:
                                attrs = case_vtx[0].get("attributes", case_vtx[0]) if isinstance(case_vtx, list) else case_vtx.get("attributes", case_vtx)
                                found_cases.append({
                                    "case_id": case_id,
                                    "outcome": attrs.get("outcome", ""),
                                    "pattern": attrs.get("pattern", ""),
                                    "exposure_usd": attrs.get("exposure_usd", 0),
                                    "analyst_notes": attrs.get("analyst_notes", ""),
                                })
                                all_entity_ids.append(case_id)
                        except Exception:
                            pass
            except Exception:
                pass

            try:
                # Try looking up as card → CONNECTED_CASE edge
                edges = conn.getEdges("Card", entity_id, "CONNECTED_CASE")
                for edge in edges:
                    case_id = edge.get("to_id", "")
                    if case_id and case_id not in [c["case_id"] for c in found_cases]:
                        all_entity_ids.append(case_id)
                        found_cases.append({"case_id": case_id})
            except Exception:
                pass

        if not found_cases:
            claim = f"No prior closed cases found touching entities: {', '.join(entity_ids)}"
        else:
            case_ids = [c["case_id"] for c in found_cases]
            fraud_cases = [c for c in found_cases if c.get("outcome") == "confirmed_fraud"]
            claim = (
                f"Found {len(found_cases)} prior closed case(s) ({', '.join(case_ids)}), "
                f"{len(fraud_cases)} confirmed fraud"
            )

        return {
            "claim": claim,
            "source": "graph",
            "ref": f"query:closed_case_lookup(entity_ids={entity_ids})",
            "entity_ids": all_entity_ids,
            "_cases": found_cases,
        }

    # ── Tool 6: vector_search ────────────────────────────────────────────────

    def vector_search(
        self,
        query_text: str,
        chunk_type: str = "PolicyChunk",
        k: int = 3,
        query_embedding: Optional[List[float]] = None,
    ) -> Dict[str, Any]:
        """
        Vector top-k search over PolicyChunk / PatternChunk /
        ClosedCase analyst_notes / RegDoc.
        """
        self._tool_call_count += 1
        conn = self._get_conn()

        if query_embedding is None:
            # Compute embedding locally if not provided
            try:
                from sentence_transformers import SentenceTransformer
                model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
                query_embedding = model.encode(query_text).tolist()
            except Exception as e:
                logger.error(f"Failed to compute embedding: {e}")
                return {
                    "claim": f"Vector search failed: could not compute embedding",
                    "source": "document",
                    "ref": f"query:vector_search(chunk_type={chunk_type}, k={k})",
                    "entity_ids": [],
                }

        try:
            # Use TigerGraph's vector search
            result = conn.runInstalledQuery("vector_search", params={
                "query_embedding": query_embedding,
                "chunk_type": chunk_type,
                "k": k,
            })
        except Exception as e:
            logger.warning(f"Vector search query failed: {e}")
            result = []

        entity_ids = []
        chunks = []
        for item in result:
            if isinstance(item, dict):
                v_id = item.get("v_id", item.get("doc_id", item.get("rule_id", "")))
                text = item.get("text", item.get("chunk_text", item.get("analyst_notes", "")))
                entity_ids.append(v_id)
                chunks.append({"id": v_id, "text": text[:500]})

        if not chunks:
            claim = f"No relevant {chunk_type} chunks found for: '{query_text[:100]}'"
        else:
            chunk_ids = [c["id"] for c in chunks]
            claim = f"Retrieved {len(chunks)} {chunk_type} chunk(s): {', '.join(chunk_ids)}"

        source = "document" if chunk_type in ("RegDoc", "PolicyChunk", "PatternChunk") else "graph"

        return {
            "claim": claim,
            "source": source,
            "ref": f"query:vector_search(chunk_type={chunk_type}, k={k})",
            "entity_ids": entity_ids,
            "_chunks": chunks,
        }

    # ── Tool 7: write_case ───────────────────────────────────────────────────

    def write_case(
        self, case_json: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Upsert a Case vertex + all edges (OPENED_FOR, AFFECTS, LINKS_CARD,
        CITES, APPLIED_RULE).

        Returns confirmation with graph_case_id.
        """
        self._tool_call_count += 1
        conn = self._get_conn()

        case_id = case_json.get("case_id", "")
        case_detail = case_json.get("case", {})

        try:
            # Upsert Case vertex
            conn.upsertVertex("InvestigationCase", case_id, attributes={
                "status": case_detail.get("status", "open"),
                "verdict": case_detail.get("verdict", "uncertain"),
                "fraud_probability": case_detail.get("fraud_probability", 0.0),
                "pattern": case_detail.get("pattern", "none"),
                "pattern_description": case_detail.get("pattern_description", ""),
                "exposure_usd": case_detail.get("exposure_usd", 0.0),
                "summary": case_detail.get("summary", ""),
                "created_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                "updated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            })

            # OPENED_FOR edge: Case -> flagged Transaction
            flagged_txn = case_json.get("_flagged_txn_id", "")
            if flagged_txn:
                conn.upsertEdge("InvestigationCase", case_id, "OPENED_FOR", "Transaction", flagged_txn)

            # AFFECTS edges: Case -> all affected transactions
            for txn_id in case_detail.get("affected_txn_ids", []):
                conn.upsertEdge("InvestigationCase", case_id, "AFFECTS", "Transaction", txn_id)

            # LINKS_CARD edges: Case -> connected cards
            for card_id in case_detail.get("connected_card_ids", []):
                conn.upsertEdge("InvestigationCase", case_id, "LINKS_CARD", "Card", card_id)

            # CITES edges: Case -> similar prior closed cases
            for prior_case_id in case_detail.get("similar_prior_cases", []):
                conn.upsertEdge("InvestigationCase", case_id, "CITES", "ClosedCase", prior_case_id)

            # APPLIED_RULE edges: extract rule IDs from action reasons
            applied_rules = set()
            for action_list_key in ("initial", "final"):
                nba = case_json.get("next_best_actions", {})
                for action in nba.get(action_list_key, []):
                    reason = action.get("reason", "")
                    # Extract rule citations like "R1", "R2", etc.
                    for i in range(1, 11):
                        if f"R{i}" in reason:
                            applied_rules.add(f"R{i}")
            for rule_id in applied_rules:
                conn.upsertEdge("InvestigationCase", case_id, "APPLIED_RULE", "PolicyChunk", rule_id)

            graph_case_id = case_id
            logger.info(f"Case {case_id} written to TigerGraph successfully.")

        except Exception as e:
            logger.error(f"Failed to write case {case_id} to TigerGraph: {e}")
            graph_case_id = ""

        return {
            "graph_case_id": graph_case_id,
            "written_to_graph": bool(graph_case_id),
        }

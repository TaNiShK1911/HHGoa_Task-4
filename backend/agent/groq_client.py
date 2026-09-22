"""
Groq API wrapper — Section 2 of the implementation plan.

Thin wrapper around Groq's OpenAI-compatible chat completions API.
- llama-3.3-70b-versatile: evidence synthesis, pattern naming, SAR narrative
- llama-3.1-8b-instant: cheap sub-classification (single-signal check)

Includes exponential backoff/retry for rate limiting and token counting.
"""

from __future__ import annotations

import os
import time
import logging
from typing import Any, Dict, List, Optional

from groq import Groq, RateLimitError

logger = logging.getLogger(__name__)

# Model identifiers
MODEL_LARGE = "openai/gpt-oss-120b"
MODEL_SMALL = "openai/gpt-oss-20b"

# Retry configuration
MAX_RETRIES = 5
INITIAL_BACKOFF_S = 1.0
BACKOFF_FACTOR = 2.0


class GroqClient:
    """
    Wrapper around the Groq SDK with retry logic and token tracking.

    Usage:
        client = GroqClient()
        response, tokens = client.chat(
            model="large",
            system_prompt="You are a fraud analyst.",
            user_prompt="Summarize the evidence...",
        )
    """

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or os.environ.get("GROQ_API_KEY", "")
        if not self._api_key:
            logger.warning(
                "GROQ_API_KEY not set. LLM calls will fail at runtime."
            )
        self._client = Groq(api_key=self._api_key) if self._api_key else None
        self._total_tokens = 0

    @property
    def total_tokens(self) -> int:
        """Total tokens consumed across all calls in this client's lifetime."""
        return self._total_tokens

    def reset_token_count(self) -> None:
        """Reset the token counter (call at the start of each case)."""
        self._total_tokens = 0

    def chat(
        self,
        model: str = "large",
        system_prompt: str = "",
        user_prompt: str = "",
        messages: Optional[List[Dict[str, str]]] = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> tuple[str, int]:
        """
        Send a chat completion request to Groq.

        Args:
            model: "large" for llama-3.3-70b-versatile,
                   "small" for llama-3.1-8b-instant.
            system_prompt: System-level instructions.
            user_prompt: The user message.
            messages: Optional full message list (overrides system/user prompts).
            temperature: Sampling temperature.
            max_tokens: Maximum tokens in the response.

        Returns:
            (response_text, tokens_used) tuple.
        """
        if not self._client:
            raise RuntimeError(
                "Groq client not initialized. Set GROQ_API_KEY."
            )

        model_id = MODEL_LARGE if model == "large" else MODEL_SMALL

        if messages is None:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": user_prompt})

        backoff = INITIAL_BACKOFF_S
        last_error = None

        for attempt in range(MAX_RETRIES):
            try:
                response = self._client.chat.completions.create(
                    model=model_id,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                content = response.choices[0].message.content or ""
                tokens = response.usage.total_tokens if response.usage else 0
                self._total_tokens += tokens
                return content, tokens

            except RateLimitError as e:
                last_error = e
                logger.warning(
                    f"Rate limited (attempt {attempt + 1}/{MAX_RETRIES}). "
                    f"Retrying in {backoff:.1f}s..."
                )
                time.sleep(backoff)
                backoff *= BACKOFF_FACTOR

            except Exception as e:
                last_error = e
                logger.error(f"Groq API error: {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(backoff)
                    backoff *= BACKOFF_FACTOR

        raise RuntimeError(
            f"Failed after {MAX_RETRIES} retries: {last_error}"
        )

    def assess_evidence(
        self,
        evidence_list: List[Dict[str, Any]],
        case_context: Dict[str, Any],
        similar_cases: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        ASSESS node: Synthesize evidence into pattern, probability, and rationale.

        This is the ONLY place the LLM reasons about evidence. It does NOT
        decide actions — that's the policy engine's job.

        Returns:
            {
                "pattern": str,
                "pattern_description": str,  # only if undocumented
                "fraud_probability": float,
                "rationale": str,
                "summary": str,
            }
        """
        import json

        system_prompt = """You are a senior fraud analyst. Analyze the evidence provided and determine:
1. The fraud pattern (one of: card_testing, card_not_present_fraud, card_not_present_new_device, out_of_region_use, account_takeover, undocumented, none)
2. If undocumented, describe the pattern in 2-3 sentences
3. The probability this is fraud (0.0 to 1.0) based on evidence, not the risk score
4. Your rationale in 2-3 sentences
5. A summary an analyst could read in 2-6 sentences

The risk_score is an input signal, not an answer. Your fraud_probability should reflect what the evidence shows.

Respond in JSON format:
{
    "pattern": "...",
    "pattern_description": "",
    "fraud_probability": 0.XX,
    "rationale": "...",
    "summary": "..."
}"""

        user_prompt = f"""Case Context:
{json.dumps(case_context, indent=2, default=str)}

Evidence gathered:
{json.dumps(evidence_list, indent=2, default=str)}

Similar prior cases retrieved:
{json.dumps(similar_cases, indent=2, default=str)}

Analyze this evidence and provide your assessment."""

        response_text, tokens = self.chat(
            model="large",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.2,
            max_tokens=1024,
        )

        # Parse JSON response
        try:
            # Handle potential markdown code blocks
            cleaned = response_text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1]
                cleaned = cleaned.rsplit("```", 1)[0]
            result = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse LLM response as JSON: {response_text}")
            result = {
                "pattern": "none",
                "pattern_description": "",
                "fraud_probability": 0.5,
                "rationale": response_text,
                "summary": response_text[:500],
            }

        return result

    def write_sar_narrative(
        self,
        case_detail: Dict[str, Any],
        evidence_list: List[Dict[str, Any]],
        reg_doc_chunks: List[str],
    ) -> str:
        """
        SAR_WRITE node: Generate a SAR narrative grounded on FinCEN guidance.

        The narrative must answer: who, what, when, where, how, and why suspicious.
        Six to twelve sentences, standing on its own.
        """
        import json

        system_prompt = """You are writing a Suspicious Activity Report (SAR) narrative for regulatory filing. Follow FinCEN SAR Narrative Guidance:

1. WHO: Name the customer(s), card(s), device(s), and any merchants involved
2. WHAT: Describe the suspicious activity clearly and factually
3. WHEN: Specify dates and times
4. WHERE: Mention channels (online/in-person), regions, countries
5. HOW: Explain the method (card testing, account takeover, etc.)
6. WHY: State why this activity is suspicious based on the evidence

Write 6-12 sentences. Be factual and specific. This goes to a regulator and must stand on its own. Do not include speculation — only evidence-supported claims.

Regulatory context:
""" + "\n".join(reg_doc_chunks[:3])

        user_prompt = f"""Case details:
{json.dumps(case_detail, indent=2, default=str)}

Evidence:
{json.dumps(evidence_list, indent=2, default=str)}

Write the SAR narrative."""

        narrative, tokens = self.chat(
            model="large",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.2,
            max_tokens=1024,
        )

        return narrative.strip()

    def classify_single_signal(
        self,
        evidence_list: List[Dict[str, Any]],
    ) -> bool:
        """
        SINGLE_SIGNAL_CHECK: Cheap classification — is the case resting on
        a single signal only? Uses the small model for speed.
        """
        import json

        system_prompt = """Determine if this fraud investigation is resting on a single signal (e.g., only a risk score, or only one piece of evidence). Respond with only "true" or "false".

A single signal means the case has only one independent piece of evidence supporting it. Multiple evidence items from the same source (e.g., multiple graph queries returning the same data point) count as one signal."""

        user_prompt = f"""Evidence items:
{json.dumps(evidence_list, indent=2, default=str)}

Is this case resting on a single signal? Respond with only "true" or "false"."""

        response, tokens = self.chat(
            model="small",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.0,
            max_tokens=10,
        )

        return response.strip().lower() == "true"

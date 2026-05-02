"""
Vera's composition engine — wraps OpenAI API calls with prompt routing,
retry logic, and output validation.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from openai import OpenAI, APIError

from .output_validator import ComposedMessage, parse_and_validate, parse_reply_action
from .prompt_builder import SYSTEM_PROMPT, build_compose_prompt, build_reply_prompt

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "gpt-4o"
_REPLY_MODEL = "gpt-4o-mini"
_MAX_TOKENS_COMPOSE = 1024
_MAX_TOKENS_REPLY = 512


class VeraComposer:
    """
    Stateless composition engine. All context is supplied per-call.

    Uses GPT-4o with temperature=0 for determinism.
    Retries once on parse failure before returning None.
    """

    def __init__(self, model: str = _DEFAULT_MODEL) -> None:
        self._client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self._model = model

    # ------------------------------------------------------------------
    # Primary composition (first outbound message)
    # ------------------------------------------------------------------

    def compose(
        self,
        category: dict,
        merchant: dict,
        trigger: dict,
        customer: Optional[dict] = None,
        conversation_history: Optional[list[dict]] = None,
    ) -> Optional[ComposedMessage]:
        """
        Compose an outbound message from the 4 context layers.
        Returns None only if both attempts fail.
        """
        prompt = build_compose_prompt(
            category, merchant, trigger, customer, conversation_history
        )

        for attempt in range(2):
            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    max_tokens=_MAX_TOKENS_COMPOSE,
                    temperature=0,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                )
                raw = response.choices[0].message.content
                result = parse_and_validate(raw, trigger)
                if result:
                    return result
                logger.warning("Attempt %d: parse failed, retrying", attempt + 1)
            except APIError as exc:
                logger.error("OpenAI API error on attempt %d: %s", attempt + 1, exc)
                if attempt == 1:
                    raise

        return None

    # ------------------------------------------------------------------
    # Reply composition (multi-turn)
    # ------------------------------------------------------------------

    def compose_reply(
        self,
        conv_history: list[dict],
        merchant_message: str,
        merchant: dict,
        category: dict,
        intent: str,
        is_auto: bool,
    ) -> dict:
        """
        Compose a reply to a merchant (or customer) message.
        Returns a dict with keys: action, body?, cta?, wait_seconds?, rationale.
        """
        prompt = build_reply_prompt(
            conv_history=conv_history,
            merchant_message=merchant_message,
            merchant=merchant,
            category=category,
            intent=intent,
            is_auto=is_auto,
        )

        try:
            response = self._client.chat.completions.create(
                model=_REPLY_MODEL,
                max_tokens=_MAX_TOKENS_REPLY,
                temperature=0,
                timeout=12,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
            raw = response.choices[0].message.content
            return parse_reply_action(raw)
        except APIError as exc:
            logger.error("OpenAI API error in compose_reply: %s", exc)
            return {
                "action": "send",
                "body": "Got it — let me follow up shortly.",
                "cta": "open_ended",
                "rationale": "Fallback due to API error",
            }

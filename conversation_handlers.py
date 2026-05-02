"""
Multi-turn conversation handlers (optional submission — §7.4 of challenge brief).

Demonstrates:
  - Auto-reply detection and graceful exit
  - Intent transition (qualify → action mode)
  - Hostile / off-topic handling
  - Conversation state management

Usage:
    from conversation_handlers import respond

    reply = respond(state, merchant_message="Yes, go ahead!")
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional

from dotenv import load_dotenv

from composer import VeraComposer
from conversation.auto_reply import is_auto_reply
from conversation.intent import Intent, detect_intent

load_dotenv()
_composer = VeraComposer()


@dataclass
class ConversationState:
    """
    Minimal conversation state for multi-turn handling.
    Mirrors the server-side ConversationState but serialisable.
    """
    conversation_id: str
    merchant_id: str
    merchant: dict
    category: dict
    trigger: Optional[dict] = None
    customer: Optional[dict] = None

    turns: list[dict] = field(default_factory=list)  # [{"from": "vera"|"merchant", "body": "..."}]
    is_ended: bool = False
    auto_reply_count: int = 0
    vera_bodies: list[str] = field(default_factory=list)
    last_intent: Optional[str] = None


def respond(state: ConversationState, merchant_message: str) -> dict:
    """
    Given the conversation so far + the merchant's latest message, produce the reply.

    Returns:
        {"action": "send", "body": "...", "cta": "...", "rationale": "..."}
        {"action": "wait", "wait_seconds": N, "rationale": "..."}
        {"action": "end", "rationale": "..."}
    """
    if state.is_ended:
        return {"action": "end", "rationale": "Conversation already ended"}

    prior_merchant_messages = [
        t["body"] for t in state.turns if t["from"] == "merchant"
    ]

    # Record this turn
    state.turns.append({"from": "merchant", "body": merchant_message})

    # Auto-reply detection
    if is_auto_reply(merchant_message, prior_merchant_messages):
        state.auto_reply_count += 1
        if state.auto_reply_count >= 2:
            state.is_ended = True
            result = _composer.compose_reply(
                conv_history=state.turns[-4:],
                merchant_message=merchant_message,
                merchant=state.merchant,
                category=state.category,
                intent="dismiss",
                is_auto=True,
            )
            return {"action": "end", "rationale": result.get("rationale", "Auto-reply detected — graceful exit")}

        # First auto-reply: one polite probe
        result = _composer.compose_reply(
            conv_history=state.turns[-4:],
            merchant_message=merchant_message,
            merchant=state.merchant,
            category=state.category,
            intent="auto_reply_probe",
            is_auto=False,
        )
        body = result.get("body", "")
        if body:
            state.turns.append({"from": "vera", "body": body})
            state.vera_bodies.append(body)
        return {
            "action": "send",
            "body": body,
            "cta": "open_ended",
            "rationale": "Polite probe after first auto-reply",
        }

    # Intent detection
    intent = detect_intent(merchant_message)
    state.last_intent = intent.value

    # Dismiss
    if intent == Intent.DISMISS:
        state.is_ended = True
        result = _composer.compose_reply(
            conv_history=state.turns[-4:],
            merchant_message=merchant_message,
            merchant=state.merchant,
            category=state.category,
            intent="dismiss",
            is_auto=False,
        )
        return {"action": "end", "rationale": result.get("rationale", "Graceful exit on dismiss")}

    # Normal or action intent
    result = _composer.compose_reply(
        conv_history=state.turns[-4:],
        merchant_message=merchant_message,
        merchant=state.merchant,
        category=state.category,
        intent=intent.value,
        is_auto=False,
    )

    action = result.get("action", "send")

    if action == "end":
        state.is_ended = True
        return {"action": "end", "rationale": result.get("rationale", "")}

    if action == "wait":
        return {
            "action": "wait",
            "wait_seconds": result.get("wait_seconds", 1800),
            "rationale": result.get("rationale", ""),
        }

    body = result.get("body", "")
    if body:
        state.turns.append({"from": "vera", "body": body})
        state.vera_bodies.append(body)

    return {
        "action": "send",
        "body": body,
        "cta": result.get("cta", "open_ended"),
        "rationale": result.get("rationale", ""),
    }

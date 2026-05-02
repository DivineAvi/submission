"""
Vera Bot — magicpin AI Challenge submission
==========================================
FastAPI server exposing the 5 judge-harness endpoints.

Run:
    uvicorn bot:app --host 0.0.0.0 --port 8080

Endpoints:
    POST /v1/context   — receive context pushes (idempotent by version)
    POST /v1/tick      — periodic wake-up; bot returns proactive actions
    POST /v1/reply     — receive merchant/customer reply; bot returns next move
    GET  /v1/healthz   — liveness probe
    GET  /v1/metadata  — bot identity

Also exports a standalone compose() function compatible with §7.1 of the brief.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from composer import VeraComposer
from conversation import ConversationManager, detect_intent
from conversation.auto_reply import is_auto_reply
from storage import ContextStore

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("vera_bot")

# ---------------------------------------------------------------------------
# Singletons
# ---------------------------------------------------------------------------
app = FastAPI(title="Vera Bot", version="1.0.0")
_store = ContextStore()
_conv_manager = ConversationManager()
_composer = VeraComposer()
_START_TIME = time.time()

# Track which (merchant_id, trigger_id) pairs have already fired this session
# to prevent duplicate sends across ticks.
_fired: set[str] = set()


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

class ContextBody(BaseModel):
    scope: str
    context_id: str
    version: int
    payload: dict[str, Any]
    delivered_at: str


class TickBody(BaseModel):
    now: str
    available_triggers: list[str] = []


class ReplyBody(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: str = "merchant"
    message: str
    received_at: str
    turn_number: int = 1


# ---------------------------------------------------------------------------
# GET /v1/healthz
# ---------------------------------------------------------------------------

@app.get("/v1/healthz")
def healthz() -> dict:
    counts = _store.counts()
    return {
        "status": "ok",
        "uptime_seconds": int(time.time() - _START_TIME),
        "contexts_loaded": counts,
    }


# ---------------------------------------------------------------------------
# GET /v1/metadata
# ---------------------------------------------------------------------------

@app.get("/v1/metadata")
def metadata() -> dict:
    return {
        "team_name": "Vera Enhanced",
        "team_members": ["Abhinav Kumar"],
        "model": "gpt-4o",
        "approach": (
            "4-context composition with trigger-kind routing. "
            "Each trigger kind has a dedicated prompt frame that anchors on the most "
            "specific verifiable fact from the context. "
            "Multi-turn: auto-reply detection + intent-based routing. "
            "Temperature=0 for determinism."
        ),
        "contact_email": "aviaryapanwar@gmail.com",
        "version": "1.0.0",
        "submitted_at": datetime.utcnow().isoformat() + "Z",
    }


# ---------------------------------------------------------------------------
# POST /v1/context
# ---------------------------------------------------------------------------

@app.post("/v1/context")
def push_context(body: ContextBody) -> dict:
    if body.scope not in ContextStore.VALID_SCOPES:
        raise HTTPException(
            status_code=400,
            detail={"accepted": False, "reason": "invalid_scope", "details": f"scope must be one of {ContextStore.VALID_SCOPES}"},
        )

    try:
        accepted, current_version = _store.upsert(
            scope=body.scope,
            context_id=body.context_id,
            version=body.version,
            payload=body.payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"accepted": False, "reason": str(exc)})

    if not accepted:
        return {
            "accepted": False,
            "reason": "stale_version",
            "current_version": current_version,
        }

    ack_id = f"ack_{body.context_id}_v{body.version}"
    logger.info("Context stored: scope=%s id=%s v%d", body.scope, body.context_id, body.version)
    return {
        "accepted": True,
        "ack_id": ack_id,
        "stored_at": datetime.utcnow().isoformat() + "Z",
    }


# ---------------------------------------------------------------------------
# POST /v1/tick
# ---------------------------------------------------------------------------

@app.post("/v1/tick")
def tick(body: TickBody) -> dict:
    actions: list[dict] = []

    for trigger_id in body.available_triggers:
        trigger = _store.get("trigger", trigger_id)
        if not trigger:
            continue

        merchant_id = trigger.get("merchant_id")
        if not merchant_id:
            continue

        # Dedup: skip if already fired this session
        fire_key = f"{merchant_id}::{trigger_id}"
        if fire_key in _fired:
            continue

        merchant = _store.get("merchant", merchant_id)
        if not merchant:
            continue

        category_slug = merchant.get("category_slug", "")
        category = _store.get("category", category_slug)
        if not category:
            continue

        # Customer context (for customer-scoped triggers)
        customer_id = trigger.get("customer_id")
        customer = _store.get("customer", customer_id) if customer_id else None

        # Check expiry
        expires_at = trigger.get("expires_at", "")
        if expires_at and expires_at < body.now:
            logger.debug("Trigger %s expired (%s), skipping", trigger_id, expires_at)
            continue

        # Compose
        try:
            result = _composer.compose(
                category=category,
                merchant=merchant,
                trigger=trigger,
                customer=customer,
            )
        except Exception as exc:
            logger.error("Compose error for %s/%s: %s", merchant_id, trigger_id, exc)
            continue

        if not result:
            continue

        conv_id = f"conv_{merchant_id}_{trigger_id}"
        _conv_manager.record_vera_send(conv_id, result.body)
        _fired.add(fire_key)

        # Build WhatsApp template params
        owner = merchant.get("identity", {}).get("owner_first_name", "")
        template_name = f"vera_{trigger.get('kind','generic')}_v1"
        template_params = [owner or merchant.get("identity", {}).get("name", ""), "...", "..."]

        actions.append({
            "conversation_id": conv_id,
            "merchant_id": merchant_id,
            "customer_id": customer_id,
            "send_as": result.send_as,
            "trigger_id": trigger_id,
            "template_name": template_name,
            "template_params": template_params,
            "body": result.body,
            "cta": result.cta,
            "suppression_key": result.suppression_key,
            "rationale": result.rationale,
        })

        # Limit per tick
        if len(actions) >= 20:
            break

    logger.info("Tick: %d actions returned", len(actions))
    return {"actions": actions}


# ---------------------------------------------------------------------------
# POST /v1/reply
# ---------------------------------------------------------------------------

@app.post("/v1/reply")
def reply(body: ReplyBody) -> dict:
    conv_id = body.conversation_id
    merchant_id = body.merchant_id or ""
    customer_id = body.customer_id

    merchant = _store.get("merchant", merchant_id) if merchant_id else None
    if not merchant:
        # Fallback: unknown merchant, graceful exit
        return {"action": "end", "rationale": "Unknown merchant context"}

    category_slug = merchant.get("category_slug", "")
    category = _store.get("category", category_slug) or {}

    # Process the inbound message
    signal = _conv_manager.process_merchant_reply(
        conv_id=conv_id,
        message=body.message,
        merchant_id=merchant_id,
        customer_id=customer_id,
        from_role=body.from_role,
        turn_number=body.turn_number,
    )

    state = _conv_manager.get_state(conv_id)
    history = state.recent_turns(6) if state else []

    # Route by signal
    if signal.signal == "auto_reply_end":
        _conv_manager.end(conv_id)
        return {"action": "end", "rationale": "Graceful exit after repeated auto-reply"}

    if signal.signal == "auto_reply_first":
        _conv_manager.end(conv_id)
        return {
            "action": "end",
            "rationale": "Auto-reply detected — ending conversation",
        }

    if signal.signal == "dismiss":
        _conv_manager.end(conv_id)
        return {
            "action": "end",
            "rationale": "Graceful exit on dismiss",
        }

    # Normal reply
    intent_str = signal.intent.value if signal.intent else "unknown"
    reply_result = _composer.compose_reply(
        conv_history=history,
        merchant_message=body.message,
        merchant=merchant,
        category=category,
        intent=intent_str,
        is_auto=False,
    )

    action = reply_result.get("action", "send")

    if action == "end":
        _conv_manager.end(conv_id)
        return {"action": "end", "rationale": reply_result.get("rationale", "")}

    if action == "wait":
        return {
            "action": "wait",
            "wait_seconds": reply_result.get("wait_seconds", 1800),
            "rationale": reply_result.get("rationale", ""),
        }

    body_text = reply_result.get("body", "")
    if body_text:
        _conv_manager.record_vera_send(conv_id, body_text)

    return {
        "action": "send",
        "body": body_text,
        "cta": reply_result.get("cta", "open_ended"),
        "rationale": reply_result.get("rationale", ""),
    }


# ---------------------------------------------------------------------------
# POST /v1/teardown  (optional — wipe state on test end)
# ---------------------------------------------------------------------------

@app.post("/v1/teardown")
def teardown() -> dict:
    _store.clear()
    _fired.clear()
    logger.info("Teardown complete — state wiped")
    return {"status": "wiped"}


# ---------------------------------------------------------------------------
# Standalone compose() — §7.1 of challenge brief
# ---------------------------------------------------------------------------

def compose(
    category: dict,
    merchant: dict,
    trigger: dict,
    customer: dict | None = None,
) -> dict:
    """
    Standalone compose function.
    Inputs are raw dicts loaded from the dataset JSON.
    Returns dict with keys: body, cta, send_as, suppression_key, rationale.
    Temperature=0 ensures determinism.
    Must complete in < 30s per call.
    """
    result = _composer.compose(
        category=category,
        merchant=merchant,
        trigger=trigger,
        customer=customer,
    )
    if result:
        return result.to_dict()
    return {
        "body": "",
        "cta": "none",
        "send_as": "vera",
        "suppression_key": trigger.get("suppression_key", ""),
        "rationale": "Composition failed",
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("bot:app", host="0.0.0.0", port=port, reload=False)

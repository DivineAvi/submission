"""Conversation state machine for multi-turn merchant/customer interactions."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .auto_reply import is_auto_reply
from .intent import Intent, detect_intent


@dataclass
class Turn:
    from_role: str   # "vera" | "merchant" | "customer"
    body: str
    ts: datetime = field(default_factory=datetime.utcnow)
    turn_number: int = 0


@dataclass
class ConversationState:
    conversation_id: str
    merchant_id: str
    customer_id: Optional[str]
    trigger_id: Optional[str] = None
    turns: list[Turn] = field(default_factory=list)
    is_ended: bool = False
    auto_reply_count: int = 0
    vera_bodies: list[str] = field(default_factory=list)  # for anti-repetition
    last_merchant_intent: Optional[Intent] = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    def merchant_messages(self) -> list[str]:
        return [t.body for t in self.turns if t.from_role in ("merchant", "customer")]

    def recent_turns(self, n: int = 6) -> list[dict]:
        return [{"from": t.from_role, "body": t.body} for t in self.turns[-n:]]


@dataclass
class ReplySignal:
    """Decoded result from process_merchant_reply."""
    signal: str    # "auto_reply_first" | "auto_reply_end" | "dismiss" | "reply"
    intent: Optional[Intent] = None
    message: str = ""
    auto_reply_count: int = 0


class ConversationManager:
    """Thread-safe conversation registry with state machine logic."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._convs: dict[str, ConversationState] = {}

    def get_or_create(
        self,
        conv_id: str,
        merchant_id: str,
        customer_id: Optional[str] = None,
        trigger_id: Optional[str] = None,
    ) -> ConversationState:
        with self._lock:
            if conv_id not in self._convs:
                self._convs[conv_id] = ConversationState(
                    conversation_id=conv_id,
                    merchant_id=merchant_id,
                    customer_id=customer_id,
                    trigger_id=trigger_id,
                )
            return self._convs[conv_id]

    def record_vera_send(self, conv_id: str, body: str, turn_number: int = 0) -> None:
        with self._lock:
            state = self._convs.get(conv_id)
            if state:
                state.turns.append(Turn("vera", body, turn_number=turn_number))
                state.vera_bodies.append(body)

    def process_merchant_reply(
        self,
        conv_id: str,
        message: str,
        merchant_id: str,
        customer_id: Optional[str] = None,
        from_role: str = "merchant",
        turn_number: int = 0,
    ) -> ReplySignal:
        """
        Processes an inbound reply.
        Records the turn, detects auto-replies and intent,
        and advances the conversation state.
        """
        with self._lock:
            state = self.get_or_create(conv_id, merchant_id, customer_id)
            state.turns.append(Turn(from_role, message, turn_number=turn_number))
            prior = state.merchant_messages()[:-1]  # exclude current

            if is_auto_reply(message, prior):
                state.auto_reply_count += 1
                if state.auto_reply_count >= 2:
                    state.is_ended = True
                    return ReplySignal("auto_reply_end", auto_reply_count=state.auto_reply_count)
                return ReplySignal("auto_reply_first", auto_reply_count=state.auto_reply_count)

            intent = detect_intent(message)
            state.last_merchant_intent = intent
            if intent == Intent.DISMISS:
                state.is_ended = True
                return ReplySignal("dismiss", intent=intent, message=message)

            return ReplySignal("reply", intent=intent, message=message)

    def get_state(self, conv_id: str) -> Optional[ConversationState]:
        return self._convs.get(conv_id)

    def is_body_repeated(self, conv_id: str, body: str) -> bool:
        state = self._convs.get(conv_id)
        return bool(state and body in state.vera_bodies)

    def end(self, conv_id: str) -> None:
        with self._lock:
            state = self._convs.get(conv_id)
            if state:
                state.is_ended = True

    def active_count(self) -> int:
        return sum(1 for s in self._convs.values() if not s.is_ended)

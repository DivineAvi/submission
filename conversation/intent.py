"""Intent detection for merchant and customer replies."""

from __future__ import annotations
from enum import Enum


class Intent(str, Enum):
    ACTION = "action"       # "yes", "go ahead", "do it", "send it", "haan karo"
    DISMISS = "dismiss"     # "not interested", "stop", "spam", "nahi chahiye"
    QUESTION = "question"   # Contains a question mark or WH-word
    ENGAGED = "engaged"     # Positive, wants to continue but no clear action signal
    UNKNOWN = "unknown"


_ACTION = [
    "yes", "sure", "ok", "okay", "go ahead", "proceed",
    "let's do it", "let's go", "do it", "send it", "send me",
    "please", "go for it", "haan", "haa", "bilkul", "theek hai",
    "karo", "kar do", "send karo", "acha", "thik hai", "sounds good",
    "great", "perfect", "absolutely", "of course", "definitely",
    "chalega", "chalte hain", "bata do",
]

_DISMISS = [
    "not interested", "no thanks", "no thank you", "stop",
    "unsubscribe", "don't contact", "dont contact", "spam",
    "useless", "nahi chahiye", "mat bhejo", "band karo",
    "remove me", "opt out", "leave me alone", "stop messaging",
    "not now", "maybe later", "no need",
]

_ENGAGE = [
    "tell me more", "how", "what", "which", "when", "where",
    "interesting", "good idea", "sounds interesting", "explain",
    "elaborate", "more details", "aur batao",
]


def detect_intent(message: str) -> Intent:
    lower = message.lower().strip()

    for phrase in _DISMISS:
        if phrase in lower:
            return Intent.DISMISS

    for phrase in _ACTION:
        if lower == phrase or lower.startswith(phrase + " ") or f" {phrase}" in lower:
            return Intent.ACTION

    if "?" in message:
        return Intent.QUESTION

    for phrase in _ENGAGE:
        if phrase in lower:
            return Intent.ENGAGED

    return Intent.UNKNOWN

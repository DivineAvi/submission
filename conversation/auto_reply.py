"""Auto-reply detection for WhatsApp Business canned responses."""

from __future__ import annotations

_PATTERNS = [
    # English
    "thank you for contacting",
    "our team will respond",
    "will get back to you",
    "automated response",
    "i am an automated",
    "this is an automated",
    "auto reply",
    "out of office",
    "unable to take your call",
    "we have received your message",
    # Hindi transliterated
    "aapki jaankari ke liye",
    "bahut-bahut shukriya",
    "main aapki yeh sabhi baatein",
    "hamari team tak pahuncha",
    "automated assistant hoon",
    "main ek automated",
]


def is_auto_reply(message: str, prior_messages: list[str] | None = None) -> bool:
    """
    Returns True if the message looks like a WhatsApp Business auto-reply.

    Detection strategy:
      1. Pattern match against known canned-response phrases (case-insensitive).
      2. Verbatim repetition: if this exact message has appeared 2+ times already,
         it's almost certainly an auto-reply.
    """
    lower = message.lower()
    for pattern in _PATTERNS:
        if pattern in lower:
            return True

    if prior_messages and prior_messages.count(message) >= 2:
        return True

    return False

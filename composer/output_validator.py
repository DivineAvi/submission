"""JSON output validation and schema enforcement for composed messages."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional


VALID_CTAS = {"open_ended", "binary_yes_stop", "none"}
VALID_SEND_AS = {"vera", "merchant_on_behalf"}


@dataclass
class ComposedMessage:
    body: str
    cta: str
    send_as: str
    suppression_key: str
    rationale: str

    def to_dict(self) -> dict:
        return {
            "body": self.body,
            "cta": self.cta,
            "send_as": self.send_as,
            "suppression_key": self.suppression_key,
            "rationale": self.rationale,
        }


def parse_and_validate(raw: str, trigger: dict) -> Optional[ComposedMessage]:
    """
    Extract and validate a ComposedMessage from raw LLM output.
    Returns None if the output is malformed or fails basic quality checks.
    """
    # Strip markdown fences if present
    raw = re.sub(r"```(?:json)?", "", raw).strip()

    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return None

    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return None

    body = str(data.get("body", "")).strip()
    if len(body) < 20:
        return None

    cta = data.get("cta", "open_ended")
    if cta not in VALID_CTAS:
        cta = "open_ended"

    send_as = data.get("send_as", "vera")
    if send_as not in VALID_SEND_AS:
        send_as = "vera"

    suppression_key = (
        data.get("suppression_key")
        or trigger.get("suppression_key", "")
    )

    rationale = str(data.get("rationale", "")).strip() or "4-context composition"

    return ComposedMessage(
        body=body,
        cta=cta,
        send_as=send_as,
        suppression_key=suppression_key,
        rationale=rationale,
    )


def parse_reply_action(raw: str) -> dict:
    """
    Parse the reply action JSON from an LLM response.
    Returns a safe fallback on failure.
    """
    raw = re.sub(r"```(?:json)?", "", raw).strip()
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return {
            "action": "send",
            "body": "Got it — let me take a look and get back to you.",
            "cta": "open_ended",
            "rationale": "Fallback reply",
        }

    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return {
            "action": "send",
            "body": "Got it — let me take a look and get back to you.",
            "cta": "open_ended",
            "rationale": "Fallback reply",
        }

    action = data.get("action", "send")
    if action not in ("send", "wait", "end"):
        action = "send"

    result: dict = {"action": action, "rationale": data.get("rationale", "")}

    if action == "send":
        body = str(data.get("body", "")).strip()
        if not body:
            body = "On it — will follow up shortly."
        result["body"] = body
        result["cta"] = data.get("cta", "open_ended")

    elif action == "wait":
        result["wait_seconds"] = int(data.get("wait_seconds", 1800))

    return result

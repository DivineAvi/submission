import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional, Tuple


@dataclass
class ContextEntry:
    scope: str
    context_id: str
    version: int
    payload: Dict[str, Any]
    stored_at: datetime


class ContextStore:
    """Thread-safe, versioned, idempotent in-memory context store."""

    VALID_SCOPES = {"category", "merchant", "customer", "trigger"}

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._store: Dict[Tuple[str, str], ContextEntry] = {}

    def upsert(
        self,
        scope: str,
        context_id: str,
        version: int,
        payload: Dict[str, Any],
    ) -> Tuple[bool, int]:
        """
        Idempotent upsert by (scope, context_id, version).

        Returns:
            (accepted, current_version)
            accepted=True  → stored (new or upgrade)
            accepted=False → stale (caller already has equal/higher version)
        """
        if scope not in self.VALID_SCOPES:
            raise ValueError(f"Invalid scope: {scope!r}")

        key = (scope, context_id)
        with self._lock:
            existing = self._store.get(key)
            if existing and existing.version >= version:
                return False, existing.version
            self._store[key] = ContextEntry(
                scope=scope,
                context_id=context_id,
                version=version,
                payload=payload,
                stored_at=datetime.utcnow(),
            )
            return True, version

    def get(self, scope: str, context_id: str) -> Optional[Dict[str, Any]]:
        key = (scope, context_id)
        entry = self._store.get(key)
        return entry.payload if entry else None

    def get_all(self, scope: str) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return {
                cid: entry.payload
                for (s, cid), entry in self._store.items()
                if s == scope
            }

    def counts(self) -> Dict[str, int]:
        counts = {s: 0 for s in self.VALID_SCOPES}
        with self._lock:
            for (scope, _) in self._store:
                if scope in counts:
                    counts[scope] += 1
        return counts

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

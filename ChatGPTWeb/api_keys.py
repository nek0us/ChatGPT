"""Persisted, revocable client API keys for the local HTTP service."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from typing import Any, Iterable

from .storage import RuntimeStorage


_VERSION = 1
_SCOPES = frozenset({"chat", "agent", "bot"})


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class ApiKeyStore:
    """Store only API-key digests while keeping operational usage in memory."""

    def __init__(self, storage: RuntimeStorage):
        self._storage = storage
        self._active_requests: dict[str, int] = {}
        self._last_used_at: dict[str, str] = {}

    def _load(self) -> dict[str, Any]:
        fallback = {"version": _VERSION, "keys": []}
        value = self._storage.read_json(self._storage.api_keys_path, fallback)
        if value.get("version") != _VERSION or not isinstance(value.get("keys"), list):
            return fallback
        return value

    def _save(self, value: dict[str, Any]) -> None:
        value["version"] = _VERSION
        self._storage.write_json_atomic(self._storage.api_keys_path, value)

    @staticmethod
    def _digest(secret: str) -> str:
        return hashlib.sha256(secret.encode("utf-8")).hexdigest()

    @staticmethod
    def _metadata(record: dict[str, Any], *, active_requests: int = 0, last_used_at: str = "") -> dict[str, Any]:
        return {
            "id": record["id"],
            "label": record["label"],
            "scopes": list(record["scopes"]),
            "max_concurrency": record["max_concurrency"],
            "created_at": record["created_at"],
            "revoked_at": record.get("revoked_at", ""),
            "active_requests": active_requests,
            "last_used_at": last_used_at,
        }

    @staticmethod
    def _validate_label(value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("key label must be a string")
        label = value.strip()
        if not 1 <= len(label) <= 80:
            raise ValueError("key label must be between 1 and 80 characters")
        return label

    @staticmethod
    def _validate_scopes(value: Any) -> list[str]:
        if value is None:
            return ["chat"]
        if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
            raise ValueError("key scopes must be a non-empty array of strings")
        scopes = sorted(set(value))
        if not set(scopes).issubset(_SCOPES):
            raise ValueError("key scopes may contain only 'chat', 'agent', and 'bot'")
        return scopes

    @staticmethod
    def _validate_max_concurrency(value: Any) -> int:
        if value is None:
            return 2
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 16:
            raise ValueError("key max_concurrency must be an integer between 1 and 16")
        return value

    def create(self, *, label: Any, scopes: Any = None, max_concurrency: Any = None) -> tuple[dict[str, Any], str]:
        record = {
            "id": f"key_{secrets.token_urlsafe(9)}",
            "label": self._validate_label(label),
            "scopes": self._validate_scopes(scopes),
            "max_concurrency": self._validate_max_concurrency(max_concurrency),
            "created_at": _timestamp(),
            "revoked_at": "",
        }
        secret = f"cwk_{secrets.token_urlsafe(32)}"
        record["digest"] = self._digest(secret)
        data = self._load()
        data["keys"].append(record)
        self._save(data)
        return self._metadata(record), secret

    def list(self, *, include_revoked: bool = False) -> list[dict[str, Any]]:
        records = []
        for record in self._load()["keys"]:
            if not isinstance(record, dict) or not isinstance(record.get("id"), str):
                continue
            if record.get("revoked_at") and not include_revoked:
                continue
            try:
                records.append(self._metadata(
                    record,
                    active_requests=self._active_requests.get(record["id"], 0),
                    last_used_at=self._last_used_at.get(record["id"], ""),
                ))
            except (KeyError, TypeError):
                continue
        return records

    def label_for(self, key_id: str) -> str:
        """Return an administrator-provided label without exposing any secret."""
        for record in self._load()["keys"]:
            if not isinstance(record, dict) or record.get("id") != key_id:
                continue
            label = record.get("label")
            return label if isinstance(label, str) else ""
        return ""

    def authenticate(self, secret: str) -> dict[str, Any] | None:
        if not secret:
            return None
        digest = self._digest(secret)
        for record in self._load()["keys"]:
            if not isinstance(record, dict) or record.get("revoked_at"):
                continue
            stored = record.get("digest")
            if isinstance(stored, str) and hmac.compare_digest(stored, digest):
                return record
        return None

    def acquire(self, record: dict[str, Any]) -> bool:
        key_id = str(record["id"])
        active = self._active_requests.get(key_id, 0)
        if active >= int(record["max_concurrency"]):
            return False
        self._active_requests[key_id] = active + 1
        self._last_used_at[key_id] = _timestamp()
        return True

    def release(self, record: dict[str, Any]) -> None:
        key_id = str(record["id"])
        active = self._active_requests.get(key_id, 0)
        if active <= 1:
            self._active_requests.pop(key_id, None)
        else:
            self._active_requests[key_id] = active - 1

    def revoke(self, key_id: str) -> dict[str, Any] | None:
        data = self._load()
        for record in data["keys"]:
            if isinstance(record, dict) and record.get("id") == key_id:
                if not record.get("revoked_at"):
                    record["revoked_at"] = _timestamp()
                    self._save(data)
                return self._metadata(record, active_requests=self._active_requests.get(key_id, 0))
        return None

    def rotate(self, key_id: str) -> tuple[dict[str, Any], str] | None:
        data = self._load()
        for record in data["keys"]:
            if not isinstance(record, dict) or record.get("id") != key_id or record.get("revoked_at"):
                continue
            secret = f"cwk_{secrets.token_urlsafe(32)}"
            record["digest"] = self._digest(secret)
            record["rotated_at"] = _timestamp()
            self._save(data)
            return self._metadata(record, active_requests=self._active_requests.get(key_id, 0)), secret
        return None

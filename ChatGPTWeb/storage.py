"""Versioned local storage for ChatGPTWeb runtime state."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


_CONVERSATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$")
_SCHEMA_VERSION = 2


class RuntimeStorage:
    """Own the complete on-disk layout for one ChatGPTWeb runtime."""

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.sessions_dir = self.root / "sessions"
        self.auth_states_dir = self.root / "auth_states"
        self.conversations_dir = self.root / "conversations"
        self.index_path = self.conversations_dir / "index.json"
        self.personas_path = self.root / "personas.json"
        self.ensure()

    def ensure(self) -> None:
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.auth_states_dir.mkdir(parents=True, exist_ok=True)
        self.conversations_dir.mkdir(parents=True, exist_ok=True)
        if not self.index_path.exists():
            self.write_json_atomic(self.index_path, {"version": _SCHEMA_VERSION, "conversations": {}})
        if not self.personas_path.exists():
            self.write_json_atomic(self.personas_path, {"version": _SCHEMA_VERSION, "personas": []})

    @staticmethod
    def write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf8")
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    @staticmethod
    def _key(value: str) -> str:
        return hashlib.sha256(value.lower().encode("utf8")).hexdigest()

    @staticmethod
    def validate_conversation_id(conversation_id: str) -> str:
        if not _CONVERSATION_ID.fullmatch(conversation_id):
            raise ValueError("conversation_id must be a non-empty safe identifier")
        return conversation_id

    def session_path(self, email: str) -> Path:
        if not email:
            raise ValueError("session email is required")
        return self.sessions_dir / f"{self._key(email)}.json"

    def auth_state_path(self, email: str) -> Path:
        if not email:
            raise ValueError("session email is required")
        return self.auth_states_dir / f"{self._key(email)}.json"

    def conversation_path(self, conversation_id: str) -> Path:
        conversation_id = self.validate_conversation_id(conversation_id)
        return self.conversations_dir / f"{self._key(conversation_id)}.json"

    def read_json(self, path: Path, fallback: Dict[str, Any]) -> Dict[str, Any]:
        try:
            value = json.loads(path.read_text("utf8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return fallback
        return value if isinstance(value, dict) else fallback

    def load_conversation(self, conversation_id: str) -> Dict[str, Any]:
        path = self.conversation_path(conversation_id)
        fallback = {
            "version": _SCHEMA_VERSION,
            "conversation_id": conversation_id,
            "account": "",
            "created_at": "",
            "updated_at": "",
            "messages": [],
        }
        value = self.read_json(path, fallback)
        if value.get("version") != _SCHEMA_VERSION or value.get("conversation_id") != conversation_id:
            return fallback
        if not isinstance(value.get("messages"), list):
            return fallback
        return value

    def save_conversation(self, conversation: Dict[str, Any]) -> None:
        conversation_id = self.validate_conversation_id(str(conversation.get("conversation_id", "")))
        conversation["version"] = _SCHEMA_VERSION
        self.write_json_atomic(self.conversation_path(conversation_id), conversation)

    def _index(self) -> Dict[str, Any]:
        fallback = {"version": _SCHEMA_VERSION, "conversations": {}}
        value = self.read_json(self.index_path, fallback)
        if value.get("version") != _SCHEMA_VERSION or not isinstance(value.get("conversations"), dict):
            return fallback
        return value

    def update_conversation_index(
        self,
        conversation_id: str,
        account: str,
        created_at: str,
        updated_at: str,
        message_count: int,
    ) -> None:
        conversation_id = self.validate_conversation_id(conversation_id)
        index = self._index()
        index["conversations"][conversation_id] = {
            "account": account,
            "created_at": created_at,
            "updated_at": updated_at,
            "message_count": message_count,
        }
        self.write_json_atomic(self.index_path, index)

    def conversation_owner(self, conversation_id: str) -> str:
        entry = self._index()["conversations"].get(conversation_id, {})
        return str(entry.get("account", "")) if isinstance(entry, dict) else ""

    def conversation_count(self, account: str) -> int:
        return sum(
            1 for entry in self._index()["conversations"].values()
            if isinstance(entry, dict) and entry.get("account") == account
        )

    def save_session(self, session: Any) -> None:
        def timestamp(value: Any) -> str:
            return value.isoformat() if isinstance(value, datetime) else ""

        data = {
            "version": _SCHEMA_VERSION,
            "email": session.email,
            "access_token": session.access_token,
            "session_token": session.session_token,
            "login_cookies": session.login_cookies,
            "last_wss": session.last_wss,
            "device_id": session.device_id,
            "mode": session.mode,
            "status": session.status if session.status in ("Stop", "Update") else "",
            "login_fail_count": session.login_fail_count,
            "max_login_failures": session.max_login_failures,
            "login_failure_kind": session.login_failure_kind,
            "last_login_error": session.last_login_error,
            "disabled_until": timestamp(session.disabled_until),
            "manual_disabled": session.manual_disabled,
            "runtime_last_closed_source": session.runtime_last_closed_source,
            "runtime_last_closed_at": timestamp(session.runtime_last_closed_at),
            "runtime_last_recovered_at": timestamp(session.runtime_last_recovered_at),
            "runtime_recovery_count": session.runtime_recovery_count,
            "persist_auth_state": session.persist_auth_state,
        }
        self.write_json_atomic(self.session_path(session.email), data)

    def load_session(self, email: str) -> Dict[str, Any] | None:
        data = self.read_json(self.session_path(email), {})
        if data.get("version") != _SCHEMA_VERSION or data.get("email", "").lower() != email.lower():
            return None
        return data

    def load_personas(self) -> List[Dict[str, str]]:
        data = self.read_json(self.personas_path, {"version": _SCHEMA_VERSION, "personas": []})
        values = data.get("personas", []) if data.get("version") == _SCHEMA_VERSION else []
        return [
            {"name": item["name"], "value": item["value"]}
            for item in values
            if isinstance(item, dict) and isinstance(item.get("name"), str) and isinstance(item.get("value"), str)
        ]

    def save_personas(self, personas: List[Dict[str, str]]) -> None:
        self.write_json_atomic(self.personas_path, {"version": _SCHEMA_VERSION, "personas": personas})

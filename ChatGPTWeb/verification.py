"""Short-lived human verification coordination for browser login flows."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4


class VerificationError(Exception):
    """Base exception for an interactive verification challenge."""


class VerificationExpiredError(VerificationError):
    """Raised when a code was not submitted before the challenge expired."""


class VerificationCancelledError(VerificationError):
    """Raised when an operator cancels a pending challenge."""


@dataclass(frozen=True)
class VerificationChallenge:
    """Metadata that a local control surface may safely display."""

    id: str
    account: str
    provider: str
    kind: str
    message: str
    created_at: datetime
    expires_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "account": self.account,
            "provider": self.provider,
            "kind": self.kind,
            "message": self.message,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }


class VerificationBroker:
    """Coordinate one short-lived human verification challenge per account.

    The broker deliberately keeps submitted codes out of snapshots and disk. It
    is transport-neutral: a local web console, CLI, MCP tool, or callback can
    all use the same ``submit`` and ``cancel`` operations.
    """

    def __init__(self, default_timeout_seconds: int = 240):
        if default_timeout_seconds <= 0:
            raise ValueError("default_timeout_seconds must be positive")
        self.default_timeout_seconds = default_timeout_seconds
        self._lock = asyncio.Lock()
        self._challenges: dict[str, VerificationChallenge] = {}
        self._account_ids: dict[str, str] = {}
        self._waiters: dict[str, asyncio.Future[str]] = {}

    async def request_code(
        self,
        account: str,
        provider: str,
        *,
        kind: str = "email_otp",
        message: str = "Enter the verification code shown by the provider.",
        timeout_seconds: int | None = None,
    ) -> str:
        """Wait for a human-submitted OTP and return it exactly once."""
        if not account:
            raise ValueError("account must not be empty")
        timeout = timeout_seconds or self.default_timeout_seconds
        if timeout <= 0:
            raise ValueError("timeout_seconds must be positive")

        loop = asyncio.get_running_loop()
        now = datetime.now(timezone.utc)
        challenge = VerificationChallenge(
            id=uuid4().hex,
            account=account,
            provider=provider,
            kind=kind,
            message=message,
            created_at=now,
            expires_at=now + timedelta(seconds=timeout),
        )
        waiter: asyncio.Future[str] = loop.create_future()
        async with self._lock:
            previous_id = self._account_ids.get(account)
            if previous_id:
                self._cancel_locked(previous_id, "superseded by a new verification request")
            self._challenges[challenge.id] = challenge
            self._account_ids[account] = challenge.id
            self._waiters[challenge.id] = waiter

        try:
            return await asyncio.wait_for(asyncio.shield(waiter), timeout=timeout)
        except asyncio.TimeoutError as error:
            await self._finish(challenge.id)
            raise VerificationExpiredError("verification challenge expired") from error
        finally:
            await self._finish(challenge.id)

    async def submit(self, challenge_id: str, code: str) -> bool:
        """Submit a numeric verification code to a currently pending challenge."""
        normalized = "".join(code.split())
        if not normalized.isdigit() or not 4 <= len(normalized) <= 12:
            raise ValueError("verification code must contain 4 to 12 digits")
        async with self._lock:
            waiter = self._waiters.get(challenge_id)
            if not waiter or waiter.done():
                return False
            waiter.set_result(normalized)
            return True

    async def cancel(self, challenge_id: str) -> bool:
        """Cancel a pending verification challenge."""
        async with self._lock:
            return self._cancel_locked(challenge_id, "verification challenge cancelled")

    async def snapshot(self) -> list[dict[str, Any]]:
        """Return safe metadata for all pending challenges, newest first."""
        async with self._lock:
            challenges = sorted(self._challenges.values(), key=lambda item: item.created_at, reverse=True)
            return [challenge.to_dict() for challenge in challenges]

    def _cancel_locked(self, challenge_id: str, message: str) -> bool:
        waiter = self._waiters.get(challenge_id)
        if not waiter or waiter.done():
            return False
        waiter.set_exception(VerificationCancelledError(message))
        return True

    async def _finish(self, challenge_id: str) -> None:
        async with self._lock:
            challenge = self._challenges.pop(challenge_id, None)
            self._waiters.pop(challenge_id, None)
            if challenge and self._account_ids.get(challenge.account) == challenge_id:
                self._account_ids.pop(challenge.account, None)

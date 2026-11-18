"""Fail-closed account health evidence for the Flow MCP authorization boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from collections.abc import Callable
from typing import Protocol

from flowx_os.flow_mcp.capabilities import (
    AdapterErrorCode,
    FlowAccountAuthorization,
    FlowAdapterError,
    _issue_flow_account_authorization,
    validate_account_ref,
)


class AccountHealthState(StrEnum):
    READY = "ready"
    DISCONNECTED = "disconnected"
    LOGGED_OUT = "logged_out"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    IDENTITY_UNVERIFIED = "identity_unverified"
    ACCOUNT_MISMATCH = "account_mismatch"


@dataclass(frozen=True, slots=True)
class FlowAccountHealthSnapshot:
    """Non-secret evidence returned by an authorized account-health provider.

    The provider must derive `account_ref` only after checking the identity through
    an authorized UI or identity source. Do not put email addresses, tokens, cookies,
    or browser storage into this object.
    """

    connected: bool
    logged_in: bool
    identity_verified: bool
    account_ref: str | None
    checked_at: datetime

    def __post_init__(self) -> None:
        if not all(isinstance(value, bool) for value in (self.connected, self.logged_in, self.identity_verified)):
            raise ValueError("account health flags must be booleans")
        if self.checked_at.tzinfo is None:
            raise ValueError("account health check time must be timezone-aware")
        if self.account_ref is not None and not validate_account_ref(self.account_ref):
            raise ValueError("account_ref must be an opaque local reference")


class FlowAccountHealthProvider(Protocol):
    async def get_snapshot(self) -> FlowAccountHealthSnapshot | None:
        """Read non-secret account evidence from an authorized source."""


@dataclass(frozen=True, slots=True)
class FlowAccountHealthResult:
    state: AccountHealthState
    checked_at: datetime
    account_ref: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.state, AccountHealthState) or self.checked_at.tzinfo is None:
            raise ValueError("account health result state and timestamp are invalid")
        if self.account_ref is not None and not validate_account_ref(self.account_ref):
            raise ValueError("account_ref must be an opaque local reference")
        if self.state is AccountHealthState.READY and not self.account_ref:
            raise ValueError("ready account health requires an account reference")

    def to_payload(self) -> dict[str, str | None]:
        """Return safe operational state without identity secrets or raw provider data."""
        return {
            "status": self.state.value,
            "checked_at": self.checked_at.astimezone(timezone.utc).isoformat(),
            "account_ref": self.account_ref,
        }


def inspect_flow_account_health(
    snapshot: FlowAccountHealthSnapshot,
    *,
    expected_account_ref: str,
    now: datetime,
    max_age: timedelta = timedelta(minutes=5),
) -> FlowAccountHealthResult:
    """Classify auth readiness from fresh evidence; never infer identity from login."""
    if not validate_account_ref(expected_account_ref):
        raise ValueError("expected_account_ref must be an opaque local reference")
    if now.tzinfo is None or max_age <= timedelta(0):
        raise ValueError("now must be timezone-aware and max_age must be positive")
    checked = snapshot.checked_at.astimezone(timezone.utc)
    current = now.astimezone(timezone.utc)
    if checked > current or current - checked > max_age:
        state = AccountHealthState.STALE
    elif not snapshot.connected:
        state = AccountHealthState.DISCONNECTED
    elif not snapshot.logged_in:
        state = AccountHealthState.LOGGED_OUT
    elif not snapshot.identity_verified or snapshot.account_ref is None:
        state = AccountHealthState.IDENTITY_UNVERIFIED
    elif snapshot.account_ref != expected_account_ref:
        state = AccountHealthState.ACCOUNT_MISMATCH
    else:
        state = AccountHealthState.READY
    return FlowAccountHealthResult(state, snapshot.checked_at, snapshot.account_ref)


def _raise_for_unhealthy(result: FlowAccountHealthResult) -> None:
    error_codes = {
        AccountHealthState.DISCONNECTED: AdapterErrorCode.ACCOUNT_DISCONNECTED,
        AccountHealthState.LOGGED_OUT: AdapterErrorCode.ACCOUNT_NOT_LOGGED_IN,
        AccountHealthState.STALE: AdapterErrorCode.ACCOUNT_HEALTH_STALE,
        AccountHealthState.IDENTITY_UNVERIFIED: AdapterErrorCode.ACCOUNT_UNVERIFIED,
        AccountHealthState.ACCOUNT_MISMATCH: AdapterErrorCode.ACCOUNT_MISMATCH,
        AccountHealthState.UNAVAILABLE: AdapterErrorCode.ACCOUNT_HEALTH_UNAVAILABLE,
    }
    raise FlowAdapterError(error_codes[result.state])


class FlowAccountHealthService:
    """Resolve account status through an injected, trusted evidence provider."""

    def __init__(
        self,
        provider: FlowAccountHealthProvider,
        *,
        expected_account_ref: str,
        max_age: timedelta = timedelta(minutes=5),
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not validate_account_ref(expected_account_ref) or max_age <= timedelta(0):
            raise ValueError("expected account reference and positive evidence age are required")
        self._provider = provider
        self._expected_account_ref = expected_account_ref
        self._max_age = max_age
        self._now = now or (lambda: datetime.now(timezone.utc))

    async def _read_snapshot(self) -> FlowAccountHealthSnapshot | None:
        try:
            snapshot = await self._provider.get_snapshot()
        except Exception:
            return None
        return snapshot if isinstance(snapshot, FlowAccountHealthSnapshot) else None

    async def inspect(self) -> FlowAccountHealthResult:
        snapshot = await self._read_snapshot()
        if snapshot is None:
            return FlowAccountHealthResult(
                AccountHealthState.UNAVAILABLE, self._now(), None
            )
        return inspect_flow_account_health(
            snapshot,
            expected_account_ref=self._expected_account_ref,
            now=self._now(),
            max_age=self._max_age,
        )

    async def authorize(self) -> FlowAccountAuthorization:
        snapshot = await self._read_snapshot()
        if snapshot is None:
            raise FlowAdapterError(AdapterErrorCode.ACCOUNT_HEALTH_UNAVAILABLE)
        result = inspect_flow_account_health(
            snapshot,
            expected_account_ref=self._expected_account_ref,
            now=self._now(),
            max_age=self._max_age,
        )
        if result.state is not AccountHealthState.READY or result.account_ref is None:
            _raise_for_unhealthy(result)
        return _issue_flow_account_authorization(
            result.account_ref,
            checked_at=result.checked_at,
            valid_until=result.checked_at + self._max_age,
        )

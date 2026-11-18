"""Transport-injected Flow MCP interface with capability and account gates."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from collections.abc import Callable
from typing import Protocol

from flowx_os.flow_mcp.capabilities import (
    AdapterConfig,
    AdapterErrorCode,
    FlowAccountAuthorization,
    FlowAdapterError,
    FlowMcpManifest,
    FlowOperation,
    SpendAuthorization,
    manifest_is_fresh,
    schema_accepts,
)


class ManifestProvider(Protocol):
    async def get_manifest(self) -> FlowMcpManifest | None:
        """Return the latest inspected manifest, or None if unavailable."""


class McpTransport(Protocol):
    async def call_tool(self, *, name: str, arguments: Mapping[str, object]) -> Mapping[str, object]:
        """Call exactly one tool declared by the inspected manifest."""


class SpendAuthorizationVerifier(Protocol):
    async def is_authorized(
        self,
        *,
        approval_ref: str,
        account_ref: str,
        operation: FlowOperation,
        max_allowed_credits: int,
    ) -> bool:
        """Verify an approval reference against a trusted human-approval store."""


class FlowAdapter(Protocol):
    async def invoke(
        self,
        operation: FlowOperation,
        arguments: Mapping[str, object],
        *,
        account: FlowAccountAuthorization,
        spend: SpendAuthorization | None = None,
    ) -> Mapping[str, object]:
        """Invoke a normalized operation only after all capability gates pass."""


class CapabilityGatedFlowAdapter:
    """Fail-closed adapter shell; no transport or manifest is configured by default."""

    def __init__(
        self,
        config: AdapterConfig,
        manifest_provider: ManifestProvider,
        transport: McpTransport,
        *,
        now: Callable[[], datetime] | None = None,
        spend_authorizer: SpendAuthorizationVerifier | None = None,
    ) -> None:
        self._config = config
        self._manifest_provider = manifest_provider
        self._transport = transport
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._spend_authorizer = spend_authorizer

    async def invoke(
        self,
        operation: FlowOperation,
        arguments: Mapping[str, object],
        *,
        account: FlowAccountAuthorization,
        spend: SpendAuthorization | None = None,
    ) -> Mapping[str, object]:
        if not self._config.enabled:
            raise FlowAdapterError(AdapterErrorCode.DISABLED)
        if not self._config.expected_server_id or not self._config.expected_account_ref:
            raise FlowAdapterError(AdapterErrorCode.CONFIGURATION_MISSING)
        if not account.verified:
            raise FlowAdapterError(AdapterErrorCode.ACCOUNT_UNVERIFIED)
        if account.account_ref != self._config.expected_account_ref:
            raise FlowAdapterError(AdapterErrorCode.ACCOUNT_MISMATCH)

        try:
            manifest = await self._manifest_provider.get_manifest()
        except Exception as exc:
            raise FlowAdapterError(AdapterErrorCode.MANIFEST_UNAVAILABLE) from exc
        if manifest is None:
            raise FlowAdapterError(AdapterErrorCode.MANIFEST_UNAVAILABLE)
        if manifest.server_id != self._config.expected_server_id:
            raise FlowAdapterError(AdapterErrorCode.SERVER_MISMATCH)
        if not manifest_is_fresh(manifest, now=self._now(), max_age=self._config.max_manifest_age):
            raise FlowAdapterError(AdapterErrorCode.MANIFEST_STALE)

        binding = manifest.bindings.get(operation)
        if binding is None:
            raise FlowAdapterError(AdapterErrorCode.CAPABILITY_UNKNOWN)
        tool = manifest.tools.get(binding.tool_name)
        if tool is None:
            raise FlowAdapterError(AdapterErrorCode.CAPABILITY_UNSUPPORTED)
        if not binding.required_inputs.issubset(tool.allowed_inputs):
            raise FlowAdapterError(AdapterErrorCode.TOOL_SCHEMA_INVALID)
        if binding.requires_spend_authorization and spend is None:
            raise FlowAdapterError(AdapterErrorCode.SPEND_AUTHORIZATION_REQUIRED)
        if binding.requires_spend_authorization and spend is not None and (
            spend.account_ref != account.account_ref or spend.operation != operation
        ):
            raise FlowAdapterError(AdapterErrorCode.SPEND_AUTHORIZATION_INVALID)
        if binding.requires_spend_authorization and spend is not None:
            if self._spend_authorizer is None:
                raise FlowAdapterError(AdapterErrorCode.SPEND_AUTHORIZATION_INVALID)
            try:
                approved = await self._spend_authorizer.is_authorized(
                    approval_ref=spend.approval_ref,
                    account_ref=spend.account_ref,
                    operation=spend.operation,
                    max_allowed_credits=spend.max_allowed_credits,
                )
            except Exception as exc:
                raise FlowAdapterError(AdapterErrorCode.SPEND_AUTHORIZATION_INVALID) from exc
            if not approved:
                raise FlowAdapterError(AdapterErrorCode.SPEND_AUTHORIZATION_INVALID)
        if not isinstance(arguments, Mapping) or any(not isinstance(key, str) for key in arguments):
            raise FlowAdapterError(AdapterErrorCode.ARGUMENTS_INVALID)
        if not binding.required_inputs.issubset(arguments) or not schema_accepts(tool.input_schema, arguments):
            raise FlowAdapterError(AdapterErrorCode.ARGUMENTS_INVALID)

        try:
            result = await self._transport.call_tool(name=binding.tool_name, arguments=dict(arguments))
        except Exception as exc:
            raise FlowAdapterError(AdapterErrorCode.TOOL_CALL_FAILED) from exc
        if not isinstance(result, Mapping):
            raise FlowAdapterError(AdapterErrorCode.TOOL_RESULT_INVALID)
        # MCP result contents are untrusted; callers must validate operation-specific output.
        return dict(result)

from datetime import datetime, timedelta, timezone
import unittest

from flowx_os.flow_mcp import (
    AdapterConfig,
    AdapterErrorCode,
    CapabilityBinding,
    CapabilityGatedFlowAdapter,
    FlowAccountAuthorization,
    FlowAdapterError,
    FlowMcpManifest,
    FlowOperation,
    McpTool,
    SpendAuthorization,
)
from flowx_os.flow_mcp.capabilities import _issue_flow_account_authorization


NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)


class FakeManifestProvider:
    def __init__(self, manifest):
        self.manifest = manifest
        self.calls = 0

    async def get_manifest(self):
        self.calls += 1
        return self.manifest


class FakeTransport:
    def __init__(self, result=None, error=None):
        self.result = {"status": "ok"} if result is None else result
        self.error = error
        self.calls = []

    async def call_tool(self, *, name, arguments):
        self.calls.append((name, arguments))
        if self.error:
            raise self.error
        return self.result


class FakeSpendAuthorizer:
    def __init__(self, approved=True):
        self.approved = approved
        self.calls = []

    async def is_authorized(self, **request):
        self.calls.append(request)
        return self.approved


def manifest(*, observed_at=NOW, spend=False):
    tool = McpTool("observed_status_tool", {
        "type": "object",
        "properties": {"project_url": {"type": "string"}},
        "required": ["project_url"],
    })
    binding = CapabilityBinding(
        FlowOperation.SESSION_STATUS,
        tool.name,
        required_inputs=frozenset({"project_url"}),
    )
    tools = {tool.name: tool}
    bindings = {FlowOperation.SESSION_STATUS: binding}
    if spend:
        gen_tool = McpTool("observed_generation_tool", {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "project_url": {"type": "string"},
                "output_dir": {"type": "string"},
                "model": {"type": "string"},
                "duration": {"type": "integer", "enum": [4, 6, 8, 10]},
                "ratio": {"type": "string", "enum": ["9:16", "16:9"]},
                "auto_confirm": {"type": "boolean", "const": True},
            },
            "required": ["prompt", "project_url", "output_dir", "duration", "ratio", "auto_confirm"],
        })
        tools[gen_tool.name] = gen_tool
        bindings[FlowOperation.VIDEO_GENERATE] = CapabilityBinding(
            FlowOperation.VIDEO_GENERATE, gen_tool.name,
            required_inputs=frozenset({"prompt"}), requires_spend_authorization=True,
        )
    return FlowMcpManifest("runtime-server-1", observed_at, tools, bindings)


class CapabilityGatedFlowAdapterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.provider = FakeManifestProvider(manifest())
        self.transport = FakeTransport()
        self.account = _issue_flow_account_authorization(
            "acct-primary", checked_at=NOW, valid_until=NOW + timedelta(minutes=5)
        )
        self.config = AdapterConfig(True, "runtime-server-1", "acct-primary")

    def adapter(self, config=None, provider=None, transport=None, spend_authorizer=None, now=None):
        return CapabilityGatedFlowAdapter(
            config or self.config, provider or self.provider, transport or self.transport,
            now=now or (lambda: NOW), spend_authorizer=spend_authorizer,
        )

    async def test_disabled_by_default_does_not_read_manifest_or_call_transport(self):
        adapter = self.adapter(AdapterConfig())
        with self.assertRaises(FlowAdapterError) as caught:
            await adapter.invoke(FlowOperation.SESSION_STATUS, {}, account=self.account)
        self.assertEqual(caught.exception.code, AdapterErrorCode.DISABLED)
        self.assertEqual(self.provider.calls, 0)
        self.assertEqual(self.transport.calls, [])

    async def test_fresh_verified_read_only_call_uses_observed_tool(self):
        result = await self.adapter().invoke(
            FlowOperation.SESSION_STATUS, {"project_url": "https://labs.google/fx/tools/flow"}, account=self.account
        )
        self.assertEqual(result, {"status": "ok"})
        self.assertEqual(self.transport.calls[0][0], "observed_status_tool")

    async def test_unverified_or_mismatched_account_fails_before_manifest(self):
        for account, expected in [
            (None, AdapterErrorCode.ACCOUNT_UNVERIFIED),
            (_issue_flow_account_authorization("acct-other", checked_at=NOW, valid_until=NOW + timedelta(minutes=5)), AdapterErrorCode.ACCOUNT_MISMATCH),
        ]:
            with self.subTest(expected=expected):
                with self.assertRaises(FlowAdapterError) as caught:
                    await self.adapter().invoke(FlowOperation.SESSION_STATUS, {}, account=account)
                self.assertEqual(caught.exception.code, expected)
        self.assertEqual(self.provider.calls, 0)

    async def test_expired_account_authorization_is_rejected_before_manifest(self):
        expired = _issue_flow_account_authorization(
            "acct-primary", checked_at=NOW - timedelta(minutes=6), valid_until=NOW - timedelta(minutes=1)
        )
        with self.assertRaises(FlowAdapterError) as caught:
            await self.adapter().invoke(FlowOperation.SESSION_STATUS, {}, account=expired)
        self.assertEqual(caught.exception.code, AdapterErrorCode.ACCOUNT_HEALTH_STALE)
        self.assertEqual(self.provider.calls, 0)

    async def test_account_authorization_expiry_during_async_gates_blocks_transport(self):
        calls = 0

        def advancing_clock():
            nonlocal calls
            calls += 1
            return NOW if calls < 3 else NOW + timedelta(minutes=6)

        transport = FakeTransport()
        with self.assertRaises(FlowAdapterError) as caught:
            await self.adapter(transport=transport, now=advancing_clock).invoke(
                FlowOperation.SESSION_STATUS, {"project_url": "x"}, account=self.account
            )
        self.assertEqual(caught.exception.code, AdapterErrorCode.ACCOUNT_HEALTH_STALE)
        self.assertEqual(transport.calls, [])

    def test_account_authorization_cannot_be_constructed_without_internal_issuer(self):
        with self.assertRaises(ValueError):
            FlowAccountAuthorization(
                "acct-primary", NOW, NOW + timedelta(minutes=5), object()
            )

    async def test_stale_manifest_fails_closed(self):
        provider = FakeManifestProvider(manifest(observed_at=NOW - timedelta(minutes=16)))
        with self.assertRaises(FlowAdapterError) as caught:
            await self.adapter(provider=provider).invoke(
                FlowOperation.SESSION_STATUS, {"project_url": "x"}, account=self.account
            )
        self.assertEqual(caught.exception.code, AdapterErrorCode.MANIFEST_STALE)
        self.assertEqual(self.transport.calls, [])

    async def test_unknown_capability_and_bad_arguments_fail_closed(self):
        for operation, args, expected in [
            (FlowOperation.MEDIA_DOWNLOAD, {}, AdapterErrorCode.CAPABILITY_UNKNOWN),
            (FlowOperation.SESSION_STATUS, {"unknown": "x"}, AdapterErrorCode.ARGUMENTS_INVALID),
            (FlowOperation.SESSION_STATUS, {}, AdapterErrorCode.ARGUMENTS_INVALID),
        ]:
            with self.subTest(expected=expected):
                with self.assertRaises(FlowAdapterError) as caught:
                    await self.adapter().invoke(operation, args, account=self.account)
                self.assertEqual(caught.exception.code, expected)
        self.assertEqual(self.transport.calls, [])

    async def test_argument_values_must_match_discovered_json_schema(self):
        with self.assertRaises(FlowAdapterError) as caught:
            await self.adapter().invoke(
                FlowOperation.SESSION_STATUS, {"project_url": 123}, account=self.account
            )
        self.assertEqual(caught.exception.code, AdapterErrorCode.ARGUMENTS_INVALID)
        self.assertEqual(self.transport.calls, [])

    def test_nested_manifest_schema_is_an_immutable_validated_snapshot(self):
        original = {
            "type": "object",
            "properties": {"mode": {"type": "string", "enum": ["safe", "fast"]}},
            "required": ["mode"],
        }
        tool = McpTool("schema_tool", original)
        original["properties"]["mode"]["enum"].append("unsafe")
        self.assertEqual(tool.input_schema["properties"]["mode"]["enum"], ("safe", "fast"))
        with self.assertRaises(TypeError):
            tool.input_schema["properties"]["mode"]["enum"] = ("unsafe",)

    def test_unsupported_manifest_schema_constraints_fail_closed_at_discovery(self):
        with self.assertRaises(ValueError):
            McpTool("unsupported", {
                "type": "object",
                "properties": {"payload": {"type": "string", "pattern": ".*"}},
            })

    def test_malformed_manifest_constraint_is_rejected_at_discovery(self):
        with self.assertRaises(ValueError):
            McpTool("malformed", {
                "type": "object",
                "properties": {"payload": {"type": "string", "minLength": "many"}},
            })

    async def test_spend_requires_operation_and_account_bound_approval(self):
        provider = FakeManifestProvider(manifest(spend=True))
        adapter = self.adapter(provider=provider)
        with self.assertRaises(FlowAdapterError) as caught:
            await adapter.invoke(FlowOperation.VIDEO_GENERATE, {"prompt": "x"}, account=self.account)
        self.assertEqual(caught.exception.code, AdapterErrorCode.SPEND_AUTHORIZATION_REQUIRED)

        wrong_scope = SpendAuthorization("approval-1", "acct-other", FlowOperation.VIDEO_GENERATE, 2)
        with self.assertRaises(FlowAdapterError) as caught:
            await adapter.invoke(
                FlowOperation.VIDEO_GENERATE, {"prompt": "x"}, account=self.account, spend=wrong_scope
            )
        self.assertEqual(caught.exception.code, AdapterErrorCode.SPEND_AUTHORIZATION_INVALID)
        self.assertEqual(self.transport.calls, [])

        authorizer = FakeSpendAuthorizer()
        transport = FakeTransport()
        spend = SpendAuthorization("approval-1", "acct-primary", FlowOperation.VIDEO_GENERATE, 2)
        await self.adapter(provider=provider, transport=transport, spend_authorizer=authorizer).invoke(
            FlowOperation.VIDEO_GENERATE,
            {"prompt": "x", "project_url": "https://labs.google/fx/tools/flow",
             "output_dir": "C:/flow-output", "duration": 8, "ratio": "9:16", "auto_confirm": True},
            account=self.account, spend=spend
        )
        self.assertEqual(authorizer.calls[0]["max_allowed_credits"], 2)
        self.assertEqual(transport.calls[0][0], "observed_generation_tool")

    async def test_spend_is_denied_when_approval_store_rejects_reference(self):
        provider = FakeManifestProvider(manifest(spend=True))
        transport = FakeTransport()
        spend = SpendAuthorization("unknown-approval", "acct-primary", FlowOperation.VIDEO_GENERATE, 1)
        with self.assertRaises(FlowAdapterError) as caught:
            await self.adapter(
                provider=provider, transport=transport, spend_authorizer=FakeSpendAuthorizer(False)
            ).invoke(FlowOperation.VIDEO_GENERATE,
                     {"prompt": "x", "project_url": "https://labs.google/fx/tools/flow",
                      "output_dir": "C:/flow-output", "duration": 8, "ratio": "9:16", "auto_confirm": True},
                     account=self.account, spend=spend)
        self.assertEqual(caught.exception.code, AdapterErrorCode.SPEND_AUTHORIZATION_INVALID)
        self.assertEqual(transport.calls, [])

    async def test_existing_job_resume_is_read_only_and_does_not_require_spend_approval(self):
        tool = McpTool("observed_resume_tool", {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "minLength": 1},
                "resume": {"type": "boolean", "const": True},
                "auto_confirm": {"type": "boolean", "const": False},
                "project_url": {"type": "string"},
                "prompt": {"type": "string"},
                "output_dir": {"type": "string"},
            },
            "required": ["project_url", "prompt", "output_dir", "job_id", "resume", "auto_confirm"],
        })
        observed = FlowMcpManifest(
            "runtime-server-1", NOW, {tool.name: tool},
            {FlowOperation.JOB_RESUME: CapabilityBinding(
                FlowOperation.JOB_RESUME, tool.name,
                required_inputs=frozenset({"job_id", "resume", "auto_confirm"}),
            )},
        )
        transport = FakeTransport({"job_id": "job-1", "status": "running"})
        result = await self.adapter(
            provider=FakeManifestProvider(observed), transport=transport,
        ).invoke(
            FlowOperation.JOB_RESUME,
            {"job_id": "job-1", "resume": True, "auto_confirm": False,
             "project_url": "https://labs.google/fx/tools/flow", "prompt": "original prompt",
             "output_dir": "C:/flow-output"},
            account=self.account,
        )
        self.assertEqual(result["status"], "running")
        self.assertEqual(transport.calls[0][0], "observed_resume_tool")

    async def test_existing_job_resume_rejects_any_submission_shaped_arguments(self):
        for arguments in [
            {"job_id": "job-1", "resume": True, "auto_confirm": True},
            {"job_id": "job-1", "resume": False, "auto_confirm": False},
            {"job_id": "job-1", "resume": True, "auto_confirm": False, "count": 2},
            {"resume": True, "auto_confirm": False},
        ]:
            with self.subTest(arguments=arguments):
                with self.assertRaises(FlowAdapterError) as caught:
                    await self.adapter().invoke(
                        FlowOperation.JOB_RESUME, arguments, account=self.account,
                    )
                self.assertEqual(caught.exception.code, AdapterErrorCode.JOB_RESUME_UNSAFE)
        self.assertEqual(self.transport.calls, [])

    async def test_transport_error_is_sanitized(self):
        transport = FakeTransport(error=RuntimeError("secret payload and cookie"))
        with self.assertRaises(FlowAdapterError) as caught:
            await self.adapter(transport=transport).invoke(
                FlowOperation.SESSION_STATUS, {"project_url": "x"}, account=self.account
            )
        self.assertEqual(caught.exception.code, AdapterErrorCode.TOOL_CALL_FAILED)
        self.assertNotIn("cookie", str(caught.exception))
        self.assertNotIn("secret payload", str(caught.exception))

    async def test_non_mapping_result_is_rejected(self):
        with self.assertRaises(FlowAdapterError) as caught:
            await self.adapter(transport=FakeTransport(result=[])).invoke(
                FlowOperation.SESSION_STATUS, {"project_url": "x"}, account=self.account
            )
        self.assertEqual(caught.exception.code, AdapterErrorCode.TOOL_RESULT_INVALID)


if __name__ == "__main__":
    unittest.main()

# backend/tests/test_procedure_executor.py
"""
Tests for the ProcedureExecutor class.

Tests execute_definition() with mock FunctionContext and mock functions.
Covers basic execution, error handling, flow control, and dry run.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.cwr.procedures.store.definitions import ProcedureDefinition, StepDefinition, OnErrorPolicy
from app.cwr.procedures.runtime.executor import ProcedureExecutor
from app.cwr.tools import fn
from app.cwr.tools.base import (
    BaseFunction,
    FunctionMeta,
    FunctionCategory,
    FunctionResult,
    FunctionStatus,
    FlowResult,
    ParameterDoc,
)
from app.cwr.tools.registry import FunctionRegistry
from app.cwr.tools.context import FunctionContext


# =============================================================================
# DUMMY FUNCTIONS FOR TESTING
# =============================================================================


class DummySearchFunction(BaseFunction):
    """Returns a canned list of search results."""
    meta = FunctionMeta(
        name="test_search",
        category=FunctionCategory.SEARCH,
        description="Test search function",
        parameters=[
            ParameterDoc(name="query", type="str", description="Search query", required=True),
            ParameterDoc(name="limit", type="int", description="Max results", required=False, default=10),
        ],
        returns="list",
        tags=["test"],
    )

    async def execute(self, ctx, **params):
        return FunctionResult.success_result(
            data=[{"id": "1", "title": "Result 1"}, {"id": "2", "title": "Result 2"}],
            message=f"Found 2 results for '{params.get('query')}'",
            items_processed=2,
        )


class DummyLogFunction(BaseFunction):
    """Simple output function that logs a message."""
    meta = FunctionMeta(
        name="test_log",
        category=FunctionCategory.OUTPUT,
        description="Test log function",
        parameters=[
            ParameterDoc(name="message", type="str", description="Message to log", required=True),
        ],
        returns="dict",
        tags=["test"],
    )

    async def execute(self, ctx, **params):
        return FunctionResult.success_result(
            data={"logged": params["message"]},
            message=f"Logged: {params['message']}",
        )


class DummyFailFunction(BaseFunction):
    """Always fails."""
    meta = FunctionMeta(
        name="test_fail",
        category=FunctionCategory.OUTPUT,
        description="Test failing function",
        parameters=[
            ParameterDoc(name="reason", type="str", description="Failure reason", required=False, default="test failure"),
        ],
        returns="dict",
        tags=["test"],
    )

    async def execute(self, ctx, **params):
        return FunctionResult.failed_result(
            error=params.get("reason", "test failure"),
            message="Function failed intentionally",
        )


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def test_registry():
    """Create a test registry with dummy functions."""
    registry = FunctionRegistry()
    registry.register(DummySearchFunction)
    registry.register(DummyLogFunction)
    registry.register(DummyFailFunction)
    return registry


@pytest.fixture
def executor():
    return ProcedureExecutor()


@pytest.fixture
def mock_session():
    """Create a mock async database session."""
    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    return session


@pytest.fixture
def org_id():
    return uuid4()


@pytest.fixture
def user_id():
    return uuid4()


def _make_definition(steps, **kwargs):
    """Helper to create a ProcedureDefinition from step dicts."""
    step_defs = []
    for s in steps:
        branches = None
        if s.get("branches"):
            branches = {
                name: [StepDefinition(
                    name=ns["name"],
                    function=ns["function"],
                    params=ns.get("params", {}),
                    on_error=OnErrorPolicy(ns.get("on_error", "fail")),
                ) for ns in nested_steps]
                for name, nested_steps in s["branches"].items()
            }
        step_defs.append(StepDefinition(
            name=s["name"],
            function=s["function"],
            params=s.get("params", {}),
            on_error=OnErrorPolicy(s.get("on_error", "fail")),
            condition=s.get("condition"),
            foreach=s.get("foreach"),
            branches=branches,
        ))
    defaults = {
        "name": "Test Procedure",
        "slug": "test-procedure",
        "steps": step_defs,
    }
    defaults.update(kwargs)
    return ProcedureDefinition(**defaults)


# =============================================================================
# BASIC EXECUTION TESTS
# =============================================================================


class TestBasicExecution:
    """Tests for basic procedure execution."""

    @pytest.mark.asyncio
    async def test_single_step_procedure(self, executor, mock_session, org_id, test_registry):
        with patch.object(fn, "get_or_none") as mock_get:
            mock_get.return_value = DummySearchFunction()

            definition = _make_definition([
                {"name": "search", "function": "test_search", "params": {"query": "test"}},
            ])

            result = await executor.execute_definition(
                session=mock_session,
                organization_id=org_id,
                definition=definition,
            )

            assert result["status"] == "completed"
            assert result["completed_steps"] == 1
            assert result["total_steps"] == 1
            assert "search" in result["step_results"]
            assert result["step_results"]["search"]["status"] == "success"

    @pytest.mark.asyncio
    async def test_multi_step_procedure(self, executor, mock_session, org_id, test_registry):
        search_fn = DummySearchFunction()
        log_fn = DummyLogFunction()

        with patch.object(fn, "get_or_none") as mock_get:
            def get_func(name):
                if name == "test_search":
                    return search_fn
                if name == "test_log":
                    return log_fn
                return None
            mock_get.side_effect = get_func

            definition = _make_definition([
                {"name": "search", "function": "test_search", "params": {"query": "hello"}},
                {"name": "log_result", "function": "test_log", "params": {"message": "done"}},
            ])

            result = await executor.execute_definition(
                session=mock_session,
                organization_id=org_id,
                definition=definition,
            )

            assert result["status"] == "completed"
            assert result["completed_steps"] == 2

    @pytest.mark.asyncio
    async def test_step_result_available_in_context(self, executor, mock_session, org_id):
        """Step results should be stored in context for subsequent steps."""
        search_fn = DummySearchFunction()
        captured_params = {}

        class CapturingLogFunction(BaseFunction):
            meta = DummyLogFunction.meta

            async def execute(self, ctx, **params):
                # Capture what the step sees from context
                captured_params["message"] = params.get("message")
                captured_params["step_result"] = ctx.get_step_result("search")
                return FunctionResult.success_result(data={"ok": True})

        with patch.object(fn, "get_or_none") as mock_get:
            def get_func(name):
                if name == "test_search":
                    return search_fn
                if name == "test_log":
                    return CapturingLogFunction()
                return None
            mock_get.side_effect = get_func

            definition = _make_definition([
                {"name": "search", "function": "test_search", "params": {"query": "test"}},
                {"name": "log_it", "function": "test_log", "params": {"message": "done"}},
            ])

            result = await executor.execute_definition(
                session=mock_session,
                organization_id=org_id,
                definition=definition,
            )

            assert result["status"] == "completed"
            # The search result should have been stored in context
            assert captured_params["step_result"] is not None


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================


class TestErrorHandling:
    """Tests for error handling policies."""

    @pytest.mark.asyncio
    async def test_on_error_fail_stops_execution(self, executor, mock_session, org_id):
        with patch.object(fn, "get_or_none") as mock_get:
            def get_func(name):
                if name == "test_fail":
                    return DummyFailFunction()
                if name == "test_log":
                    return DummyLogFunction()
                return None
            mock_get.side_effect = get_func

            definition = _make_definition([
                {"name": "failing_step", "function": "test_fail", "params": {}, "on_error": "fail"},
                {"name": "should_not_run", "function": "test_log", "params": {"message": "hi"}},
            ])

            result = await executor.execute_definition(
                session=mock_session,
                organization_id=org_id,
                definition=definition,
            )

            assert result["status"] == "failed"
            assert "failing_step" in result["failed_steps"]
            # Second step should not have a result (execution stopped)
            assert "should_not_run" not in result["step_results"]

    @pytest.mark.asyncio
    async def test_on_error_skip_continues(self, executor, mock_session, org_id):
        with patch.object(fn, "get_or_none") as mock_get:
            def get_func(name):
                if name == "test_fail":
                    return DummyFailFunction()
                if name == "test_log":
                    return DummyLogFunction()
                return None
            mock_get.side_effect = get_func

            definition = _make_definition([
                {"name": "failing_step", "function": "test_fail", "params": {}, "on_error": "skip"},
                {"name": "should_run", "function": "test_log", "params": {"message": "hi"}},
            ])

            result = await executor.execute_definition(
                session=mock_session,
                organization_id=org_id,
                definition=definition,
            )

            # Should continue past the failed step
            assert "should_run" in result["step_results"]
            assert result["step_results"]["should_run"]["status"] == "success"

    @pytest.mark.asyncio
    async def test_on_error_continue_proceeds(self, executor, mock_session, org_id):
        with patch.object(fn, "get_or_none") as mock_get:
            def get_func(name):
                if name == "test_fail":
                    return DummyFailFunction()
                if name == "test_log":
                    return DummyLogFunction()
                return None
            mock_get.side_effect = get_func

            definition = _make_definition([
                {"name": "failing_step", "function": "test_fail", "params": {}, "on_error": "continue"},
                {"name": "should_run", "function": "test_log", "params": {"message": "hi"}},
            ])

            result = await executor.execute_definition(
                session=mock_session,
                organization_id=org_id,
                definition=definition,
            )

            assert "should_run" in result["step_results"]
            assert result["step_results"]["should_run"]["status"] == "success"

    @pytest.mark.asyncio
    async def test_unknown_function_fails_step(self, executor, mock_session, org_id):
        with patch.object(fn, "get_or_none") as mock_get:
            mock_get.return_value = None

            definition = _make_definition([
                {"name": "bad_step", "function": "nonexistent", "params": {}},
            ])

            result = await executor.execute_definition(
                session=mock_session,
                organization_id=org_id,
                definition=definition,
            )

            assert result["status"] == "failed"
            assert result["step_results"]["bad_step"]["status"] == "failed"
            assert "not found" in result["step_results"]["bad_step"]["error"].lower()


# =============================================================================
# FLOW CONTROL TESTS
# =============================================================================


class TestFlowControl:
    """Tests for flow control functions (if_branch, foreach)."""

    @pytest.mark.asyncio
    async def test_if_branch_true_path(self, executor, mock_session, org_id):
        """When FlowResult has branch_key='then', execute then branch."""

        class MockIfBranch(BaseFunction):
            meta = FunctionMeta(
                name="if_branch",
                category=FunctionCategory.FLOW,
                description="If branch",
                parameters=[
                    ParameterDoc(name="condition", type="str", description="Condition", required=True),
                ],
                returns="dict",
            )

            async def execute(self, ctx, **params):
                return FlowResult.success_result(
                    branch_key="then",
                    message="Condition is true",
                )

        with patch.object(fn, "get_or_none") as mock_get:
            def get_func(name):
                if name == "if_branch":
                    return MockIfBranch()
                if name == "test_log":
                    return DummyLogFunction()
                return None
            mock_get.side_effect = get_func

            definition = _make_definition([
                {
                    "name": "decide",
                    "function": "if_branch",
                    "params": {"condition": "true"},
                    "branches": {
                        "then": [
                            {"name": "yes_action", "function": "test_log", "params": {"message": "yes"}},
                        ],
                        "else": [
                            {"name": "no_action", "function": "test_log", "params": {"message": "no"}},
                        ],
                    },
                },
            ])

            result = await executor.execute_definition(
                session=mock_session,
                organization_id=org_id,
                definition=definition,
            )

            assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_if_branch_false_path(self, executor, mock_session, org_id):
        """When FlowResult has branch_key='else', execute else branch."""

        class MockIfBranch(BaseFunction):
            meta = FunctionMeta(
                name="if_branch",
                category=FunctionCategory.FLOW,
                description="If branch",
                parameters=[
                    ParameterDoc(name="condition", type="str", description="Condition", required=True),
                ],
                returns="dict",
            )

            async def execute(self, ctx, **params):
                return FlowResult.success_result(
                    branch_key="else",
                    message="Condition is false",
                )

        with patch.object(fn, "get_or_none") as mock_get:
            def get_func(name):
                if name == "if_branch":
                    return MockIfBranch()
                if name == "test_log":
                    return DummyLogFunction()
                return None
            mock_get.side_effect = get_func

            definition = _make_definition([
                {
                    "name": "decide",
                    "function": "if_branch",
                    "params": {"condition": "false"},
                    "branches": {
                        "then": [
                            {"name": "yes_action", "function": "test_log", "params": {"message": "yes"}},
                        ],
                        "else": [
                            {"name": "no_action", "function": "test_log", "params": {"message": "no"}},
                        ],
                    },
                },
            ])

            result = await executor.execute_definition(
                session=mock_session,
                organization_id=org_id,
                definition=definition,
            )

            assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_foreach_iterates_items(self, executor, mock_session, org_id):
        """When FlowResult has items_to_iterate, execute each branch per item."""
        call_count = 0

        class MockForeach(BaseFunction):
            meta = FunctionMeta(
                name="foreach",
                category=FunctionCategory.FLOW,
                description="Foreach",
                parameters=[
                    ParameterDoc(name="items", type="list", description="Items", required=True),
                ],
                returns="dict",
            )

            async def execute(self, ctx, **params):
                items = params["items"]
                return FlowResult.success_result(
                    items_to_iterate=items,
                    message=f"Iterating {len(items)} items",
                    metadata={"concurrency": 1},
                )

        class CountingLog(BaseFunction):
            meta = DummyLogFunction.meta

            async def execute(self, ctx, **params):
                nonlocal call_count
                call_count += 1
                return FunctionResult.success_result(data={"count": call_count})

        with patch.object(fn, "get_or_none") as mock_get:
            def get_func(name):
                if name == "foreach":
                    return MockForeach()
                if name == "test_log":
                    return CountingLog()
                return None
            mock_get.side_effect = get_func

            definition = _make_definition([
                {
                    "name": "iterate",
                    "function": "foreach",
                    "params": {"items": ["a", "b", "c"]},
                    "branches": {
                        "each": [
                            {"name": "process", "function": "test_log", "params": {"message": "hi"}},
                        ],
                    },
                },
            ])

            result = await executor.execute_definition(
                session=mock_session,
                organization_id=org_id,
                definition=definition,
            )

            assert result["status"] == "completed"
            assert call_count == 3


# =============================================================================
# DRY RUN TESTS
# =============================================================================


class TestDryRun:
    """Tests for dry_run mode."""

    @pytest.mark.asyncio
    async def test_dry_run_passes_flag_to_context(self, executor, mock_session, org_id):
        """Dry run flag should be propagated to the function context."""
        captured_dry_run = None

        class DryRunCapture(BaseFunction):
            meta = DummyLogFunction.meta

            async def execute(self, ctx, **params):
                nonlocal captured_dry_run
                captured_dry_run = ctx.dry_run
                return FunctionResult.success_result(data={"dry_run": ctx.dry_run})

        with patch.object(fn, "get_or_none") as mock_get:
            mock_get.return_value = DryRunCapture()

            definition = _make_definition([
                {"name": "step_one", "function": "test_log", "params": {"message": "test"}},
            ])

            result = await executor.execute_definition(
                session=mock_session,
                organization_id=org_id,
                definition=definition,
                dry_run=True,
            )

            assert result["status"] == "completed"
            assert captured_dry_run is True


# =============================================================================
# CONDITION EVALUATION TESTS
# =============================================================================


class TestConditionEvaluation:
    """Tests for step condition evaluation."""

    @pytest.mark.asyncio
    async def test_step_skipped_when_condition_false(self, executor, mock_session, org_id):
        """Step with a false condition should be skipped."""
        with patch.object(fn, "get_or_none") as mock_get:
            mock_get.return_value = DummyLogFunction()

            definition = _make_definition([
                {
                    "name": "conditional_step",
                    "function": "test_log",
                    "params": {"message": "should not run"},
                    "condition": "false",
                },
            ])

            result = await executor.execute_definition(
                session=mock_session,
                organization_id=org_id,
                definition=definition,
            )

            assert result["status"] == "completed"
            assert result["step_results"]["conditional_step"].get("skipped") is True


# =============================================================================
# GOVERNANCE TESTS
# =============================================================================


class DummySideEffectFunction(BaseFunction):
    """Function with side_effects=True."""
    meta = FunctionMeta(
        name="test_side_effect",
        category=FunctionCategory.NOTIFY,
        description="Test function with side effects",
        parameters=[
            ParameterDoc(name="message", type="str", description="Message", required=True),
        ],
        returns="dict",
        tags=["test"],
        side_effects=True,
    )

    async def execute(self, ctx, **params):
        return FunctionResult.success_result(
            data={"sent": params["message"]},
            message=f"Sent: {params['message']}",
        )


class DummyBlockedFunction(BaseFunction):
    """Function with exposure_profile procedure=False."""
    meta = FunctionMeta(
        name="test_blocked",
        category=FunctionCategory.OUTPUT,
        description="Test function blocked from procedures",
        parameters=[
            ParameterDoc(name="data", type="str", description="Data", required=True),
        ],
        returns="dict",
        tags=["test"],
        exposure_profile={"procedure": False, "agent": True},
    )

    async def execute(self, ctx, **params):
        return FunctionResult.success_result(data={"ok": True})


class TestGovernance:
    """Tests for governance logging and enforcement."""

    @pytest.mark.asyncio
    async def test_side_effect_function_logged(self, executor, mock_session, org_id):
        """Execute step with side_effects=True function -> governance log event created."""
        log_events = []
        original_log = None

        with patch.object(fn, "get_or_none") as mock_get:
            mock_get.return_value = DummySideEffectFunction()

            definition = _make_definition([
                {"name": "send_it", "function": "test_side_effect", "params": {"message": "hello"}},
            ])

            # Patch log_run_event to capture calls
            with patch.object(FunctionContext, "log_run_event", new_callable=AsyncMock) as mock_log:
                result = await executor.execute_definition(
                    session=mock_session,
                    organization_id=org_id,
                    definition=definition,
                )

                # Find governance log events
                governance_calls = [
                    call for call in mock_log.call_args_list
                    if call.kwargs.get("event_type") == "governance"
                    or (len(call.args) >= 2 and call.args[1] == "governance")
                ]

                assert len(governance_calls) > 0
                assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_exposure_profile_blocks_function(self, executor, mock_session, org_id):
        """Function with procedure=False in exposure_profile -> step fails."""
        with patch.object(fn, "get_or_none") as mock_get:
            mock_get.return_value = DummyBlockedFunction()

            definition = _make_definition([
                {"name": "blocked_step", "function": "test_blocked", "params": {"data": "test"}},
            ])

            with patch.object(FunctionContext, "log_run_event", new_callable=AsyncMock):
                result = await executor.execute_definition(
                    session=mock_session,
                    organization_id=org_id,
                    definition=definition,
                )

                assert result["status"] == "failed"
                assert "not available in procedure context" in result["step_results"]["blocked_step"]["error"]

    @pytest.mark.asyncio
    async def test_side_effect_summary_in_results(self, executor, mock_session, org_id):
        """Procedure with side-effect steps -> results contain governance summary."""
        side_effect_fn = DummySideEffectFunction()
        log_fn = DummyLogFunction()

        with patch.object(fn, "get_or_none") as mock_get:
            def get_func(name):
                if name == "test_side_effect":
                    return side_effect_fn
                if name == "test_log":
                    return log_fn
                return None
            mock_get.side_effect = get_func

            definition = _make_definition([
                {"name": "log_first", "function": "test_log", "params": {"message": "hi"}},
                {"name": "send_it", "function": "test_side_effect", "params": {"message": "hello"}},
            ])

            with patch.object(FunctionContext, "log_run_event", new_callable=AsyncMock):
                result = await executor.execute_definition(
                    session=mock_session,
                    organization_id=org_id,
                    definition=definition,
                )

                assert result["status"] == "completed"
                assert "governance" in result
                assert "send_it" in result["governance"]["side_effect_steps"]
                assert result["governance"]["total_side_effects"] == 1

    @pytest.mark.asyncio
    async def test_no_governance_log_for_safe_function(self, executor, mock_session, org_id):
        """Function with side_effects=False -> no governance log event."""
        with patch.object(fn, "get_or_none") as mock_get:
            mock_get.return_value = DummyLogFunction()  # side_effects=False by default

            definition = _make_definition([
                {"name": "safe_step", "function": "test_log", "params": {"message": "hi"}},
            ])

            with patch.object(FunctionContext, "log_run_event", new_callable=AsyncMock) as mock_log:
                result = await executor.execute_definition(
                    session=mock_session,
                    organization_id=org_id,
                    definition=definition,
                )

                # No governance event should be logged
                governance_calls = [
                    call for call in mock_log.call_args_list
                    if call.kwargs.get("event_type") == "governance"
                    or (len(call.args) >= 2 and call.args[1] == "governance")
                ]

                assert len(governance_calls) == 0
                assert result["status"] == "completed"


# =============================================================================
# OBSERVABILITY TESTS
# =============================================================================


class TestObservability:
    """Tests for execution metrics and observability."""

    @pytest.mark.asyncio
    async def test_step_complete_includes_duration_ms(self, executor, mock_session, org_id):
        """Verify timing is recorded in step results."""
        with patch.object(fn, "get_or_none") as mock_get:
            mock_get.return_value = DummySearchFunction()

            definition = _make_definition([
                {"name": "search", "function": "test_search", "params": {"query": "test"}},
            ])

            with patch.object(FunctionContext, "log_run_event", new_callable=AsyncMock) as mock_log:
                result = await executor.execute_definition(
                    session=mock_session,
                    organization_id=org_id,
                    definition=definition,
                )

                assert result["status"] == "completed"
                # Check step result has duration_ms
                assert "duration_ms" in result["step_results"]["search"]
                assert isinstance(result["step_results"]["search"]["duration_ms"], int)
                assert result["step_results"]["search"]["duration_ms"] >= 0

    @pytest.mark.asyncio
    async def test_step_complete_includes_governance_fields(self, executor, mock_session, org_id):
        """Verify payload_profile and side_effects in step_complete log context."""
        with patch.object(fn, "get_or_none") as mock_get:
            mock_get.return_value = DummySideEffectFunction()

            definition = _make_definition([
                {"name": "send_it", "function": "test_side_effect", "params": {"message": "hi"}},
            ])

            with patch.object(FunctionContext, "log_run_event", new_callable=AsyncMock) as mock_log:
                result = await executor.execute_definition(
                    session=mock_session,
                    organization_id=org_id,
                    definition=definition,
                )

                # Find step_complete log event
                step_complete_calls = [
                    call for call in mock_log.call_args_list
                    if call.kwargs.get("event_type") == "step_complete"
                ]

                assert len(step_complete_calls) > 0
                ctx = step_complete_calls[0].kwargs.get("context", {})
                assert "payload_profile" in ctx
                assert "side_effects" in ctx
                assert ctx["side_effects"] is True
                assert "duration_ms" in ctx

# backend/tests/test_pipeline_executor.py
"""
Tests for the PipelineExecutor class.

Tests execute_definition() with mock functions and sessions.
Covers gather, filter, transform, output stages, error handling, and resume.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from app.cwr.pipelines.runtime.definitions import OnErrorPolicy, PipelineDefinition, StageDefinition, StageType
from app.cwr.pipelines.runtime.executor import PipelineExecutor
from app.cwr.tools import fn
from app.cwr.tools.base import (
    BaseFunction,
    FunctionCategory,
    FunctionMeta,
    FunctionResult,
)

# =============================================================================
# DUMMY FUNCTIONS FOR TESTING
# =============================================================================


class DummyGatherFunction(BaseFunction):
    """Returns a canned list of items."""
    meta = FunctionMeta(
        name="test_gather",
        category=FunctionCategory.SEARCH,
        description="Test gather function",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Query", "default": "*"},
            },
            "required": [],
        },
        tags=["test"],
    )

    async def execute(self, ctx, **params):
        return FunctionResult.success_result(
            data=[
                {"id": "1", "title": "Item 1", "score": 0.9},
                {"id": "2", "title": "Item 2", "score": 0.3},
                {"id": "3", "title": "Item 3", "score": 0.7},
            ],
            message="Gathered 3 items",
        )


class DummyFilterFunction(BaseFunction):
    """Filters items by returning True/False."""
    meta = FunctionMeta(
        name="test_filter",
        category=FunctionCategory.LOGIC,
        description="Test filter function",
        input_schema={
            "type": "object",
            "properties": {
                "item": {"type": "object", "description": "Item to filter"},
                "threshold": {"type": "number", "description": "Score threshold", "default": 0.5},
            },
            "required": [],
        },
        tags=["test"],
    )

    async def execute(self, ctx, **params):
        item = params.get("item", {})
        threshold = params.get("threshold", 0.5)
        passes = item.get("score", 0) >= threshold
        return FunctionResult.success_result(data=passes)


class DummyTransformFunction(BaseFunction):
    """Transforms items by adding a field."""
    meta = FunctionMeta(
        name="test_transform",
        category=FunctionCategory.OUTPUT,
        description="Test transform function",
        input_schema={
            "type": "object",
            "properties": {
                "item": {"type": "object", "description": "Item to transform"},
            },
            "required": [],
        },
        tags=["test"],
    )

    async def execute(self, ctx, **params):
        return FunctionResult.success_result(
            data={"transformed": True},
        )


class DummyOutputFunction(BaseFunction):
    """Outputs items."""
    meta = FunctionMeta(
        name="test_output",
        category=FunctionCategory.OUTPUT,
        description="Test output function",
        input_schema={
            "type": "object",
            "properties": {
                "items": {"type": "array", "description": "Items to output"},
            },
            "required": [],
        },
        tags=["test"],
    )

    async def execute(self, ctx, **params):
        items = params.get("items", [])
        return FunctionResult.success_result(
            data={"exported": len(items)},
            message=f"Exported {len(items)} items",
        )


class DummyFailTransform(BaseFunction):
    """Transform that always fails."""
    meta = FunctionMeta(
        name="test_fail_transform",
        category=FunctionCategory.OUTPUT,
        description="Test failing transform",
        input_schema={
            "type": "object",
            "properties": {
                "item": {"type": "object", "description": "Item"},
            },
            "required": [],
        },
        tags=["test"],
    )

    async def execute(self, ctx, **params):
        return FunctionResult.failed_result(error="Transform failed")


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def executor():
    return PipelineExecutor()


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    return session


@pytest.fixture
def org_id():
    return uuid4()


def _make_pipeline(stages, **kwargs):
    """Helper to create a PipelineDefinition from stage dicts."""
    stage_defs = [
        StageDefinition(
            name=s["name"],
            type=StageType(s["type"]),
            function=s["function"],
            params=s.get("params", {}),
            on_error=OnErrorPolicy(s.get("on_error", "skip")),
            batch_size=s.get("batch_size", 50),
        )
        for s in stages
    ]
    defaults = {
        "name": "Test Pipeline",
        "slug": "test-pipeline",
        "stages": stage_defs,
    }
    defaults.update(kwargs)
    return PipelineDefinition(**defaults)


# =============================================================================
# PIPELINE EXECUTION TESTS
# =============================================================================


class TestPipelineExecution:
    """Tests for basic pipeline execution."""

    @pytest.mark.asyncio
    async def test_gather_stage_produces_items(self, executor, mock_session, org_id):
        with patch.object(fn, "get_or_none") as mock_get:
            mock_get.return_value = DummyGatherFunction()

            definition = _make_pipeline([
                {"name": "gather", "type": "gather", "function": "test_gather"},
            ])

            result = await executor.execute_definition(
                session=mock_session,
                organization_id=org_id,
                definition=definition,
            )

            assert result["status"] == "completed"
            assert result["items_processed"] == 3
            assert len(result["final_items"]) == 3

    @pytest.mark.asyncio
    async def test_filter_stage_removes_items(self, executor, mock_session, org_id):
        with patch.object(fn, "get_or_none") as mock_get:
            def get_func(name):
                if name == "test_gather":
                    return DummyGatherFunction()
                if name == "test_filter":
                    return DummyFilterFunction()
                return None
            mock_get.side_effect = get_func

            definition = _make_pipeline([
                {"name": "gather", "type": "gather", "function": "test_gather"},
                {"name": "filter", "type": "filter", "function": "test_filter", "params": {"threshold": 0.5}},
            ])

            result = await executor.execute_definition(
                session=mock_session,
                organization_id=org_id,
                definition=definition,
            )

            assert result["status"] == "completed"
            # Items with score >= 0.5: "Item 1" (0.9), "Item 3" (0.7) → 2 items
            assert result["items_processed"] == 2

    @pytest.mark.asyncio
    async def test_transform_stage_modifies_items(self, executor, mock_session, org_id):
        with patch.object(fn, "get_or_none") as mock_get:
            def get_func(name):
                if name == "test_gather":
                    return DummyGatherFunction()
                if name == "test_transform":
                    return DummyTransformFunction()
                return None
            mock_get.side_effect = get_func

            definition = _make_pipeline([
                {"name": "gather", "type": "gather", "function": "test_gather"},
                {"name": "enrich", "type": "transform", "function": "test_transform"},
            ])

            result = await executor.execute_definition(
                session=mock_session,
                organization_id=org_id,
                definition=definition,
            )

            assert result["status"] == "completed"
            # All items should have the "transformed" key merged in
            for item in result["final_items"]:
                assert item.get("transformed") is True

    @pytest.mark.asyncio
    async def test_output_stage_receives_all_items(self, executor, mock_session, org_id):
        with patch.object(fn, "get_or_none") as mock_get:
            def get_func(name):
                if name == "test_gather":
                    return DummyGatherFunction()
                if name == "test_output":
                    return DummyOutputFunction()
                return None
            mock_get.side_effect = get_func

            definition = _make_pipeline([
                {"name": "gather", "type": "gather", "function": "test_gather"},
                {"name": "output", "type": "output", "function": "test_output"},
            ])

            result = await executor.execute_definition(
                session=mock_session,
                organization_id=org_id,
                definition=definition,
            )

            assert result["status"] == "completed"
            # Output stage result should show items count
            output_result = result["stage_results"]["output"]
            assert output_result["status"] == "success"

    @pytest.mark.asyncio
    async def test_multi_stage_pipeline_end_to_end(self, executor, mock_session, org_id):
        with patch.object(fn, "get_or_none") as mock_get:
            def get_func(name):
                if name == "test_gather":
                    return DummyGatherFunction()
                if name == "test_filter":
                    return DummyFilterFunction()
                if name == "test_transform":
                    return DummyTransformFunction()
                if name == "test_output":
                    return DummyOutputFunction()
                return None
            mock_get.side_effect = get_func

            definition = _make_pipeline([
                {"name": "gather", "type": "gather", "function": "test_gather"},
                {"name": "filter", "type": "filter", "function": "test_filter", "params": {"threshold": 0.5}},
                {"name": "enrich", "type": "enrich", "function": "test_transform"},
                {"name": "output", "type": "output", "function": "test_output"},
            ])

            result = await executor.execute_definition(
                session=mock_session,
                organization_id=org_id,
                definition=definition,
            )

            assert result["status"] == "completed"
            assert result["completed_stages"] == 4
            assert result["total_stages"] == 4
            # After filter, should have 2 items (score >= 0.5)
            assert result["items_processed"] == 2


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================


class TestPipelineErrorHandling:
    """Tests for pipeline error handling."""

    @pytest.mark.asyncio
    async def test_item_failure_continues_others(self, executor, mock_session, org_id):
        """With on_error=skip (default), failed items should be skipped."""
        call_count = 0

        class FailOnSecond(BaseFunction):
            meta = DummyTransformFunction.meta

            async def execute(self, ctx, **params):
                nonlocal call_count
                call_count += 1
                if call_count == 2:
                    return FunctionResult.failed_result(error="Second item fails")
                return FunctionResult.success_result(data={"ok": True})

        with patch.object(fn, "get_or_none") as mock_get:
            def get_func(name):
                if name == "test_gather":
                    return DummyGatherFunction()
                if name == "test_transform":
                    return FailOnSecond()
                return None
            mock_get.side_effect = get_func

            definition = _make_pipeline([
                {"name": "gather", "type": "gather", "function": "test_gather"},
                {"name": "transform", "type": "transform", "function": "test_transform", "on_error": "skip"},
            ])

            result = await executor.execute_definition(
                session=mock_session,
                organization_id=org_id,
                definition=definition,
            )

            # Pipeline should complete with partial success
            transform_result = result["stage_results"]["transform"]
            assert transform_result["failed"] == 1
            # Other items should have been processed
            assert transform_result["processed"] == 2

    @pytest.mark.asyncio
    async def test_stage_failure_marks_pipeline_as_failed(self, executor, mock_session, org_id):
        """When a gather stage fails, the pipeline should report non-completed status."""

        class ExplodingGather(BaseFunction):
            meta = DummyGatherFunction.meta

            async def execute(self, ctx, **params):
                raise RuntimeError("Stage exploded")

        with patch.object(fn, "get_or_none") as mock_get:
            mock_get.return_value = ExplodingGather()

            definition = _make_pipeline(
                [
                    {"name": "bad_stage", "type": "gather", "function": "test_gather"},
                ],
                on_error=OnErrorPolicy.FAIL,
            )

            result = await executor.execute_definition(
                session=mock_session,
                organization_id=org_id,
                definition=definition,
            )

            # Stage should have failed
            assert "bad_stage" in result["stage_results"]
            assert result["stage_results"]["bad_stage"]["status"] == "failed"
            assert result["status"] in ("failed", "partial")


# =============================================================================
# RESUME TESTS
# =============================================================================


class TestPipelineResume:
    """Tests for pipeline resume from checkpoint."""

    @pytest.mark.asyncio
    async def test_resume_from_checkpoint(self, executor, mock_session, org_id):
        """When resume_from_stage > 0, earlier stages should be skipped."""
        stage_calls = []

        class TrackingGather(BaseFunction):
            meta = DummyGatherFunction.meta

            async def execute(self, ctx, **params):
                stage_calls.append("gather")
                return FunctionResult.success_result(
                    data=[{"id": "1", "title": "Item"}],
                )

        class TrackingOutput(BaseFunction):
            meta = DummyOutputFunction.meta

            async def execute(self, ctx, **params):
                stage_calls.append("output")
                return FunctionResult.success_result(data={"exported": 1})

        with patch.object(fn, "get_or_none") as mock_get:
            def get_func(name):
                if name == "test_gather":
                    return TrackingGather()
                if name == "test_output":
                    return TrackingOutput()
                return None
            mock_get.side_effect = get_func

            definition = _make_pipeline([
                {"name": "gather", "type": "gather", "function": "test_gather"},
                {"name": "output", "type": "output", "function": "test_output"},
            ])

            result = await executor.execute_definition(
                session=mock_session,
                organization_id=org_id,
                definition=definition,
                resume_from_stage=1,  # Skip gather, start from output
            )

            # Gather should NOT have been called
            assert "gather" not in stage_calls
            # Output should have been called
            assert "output" in stage_calls

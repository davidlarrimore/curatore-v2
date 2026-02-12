# backend/tests/test_procedure_discovery.py
"""
Tests for the procedure discovery and startup pipeline.

Covers:
- calculate_next_trigger_at() helper
- ProcedureDefinition dataclass (from_dict / to_dict / defaults)
- ProcedureLoader filesystem scanning and JSON parsing
- ProcedureDiscoveryService registration, update, and stale cleanup
- ORM cascade/relationship configuration that prevents silent delete failures
"""

import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.cwr.procedures.store.definitions import (
    OnErrorPolicy,
    ProcedureDefinition,
    StepDefinition,
    TriggerDefinition,
)
from app.cwr.procedures.store.discovery import (
    ProcedureDiscoveryService,
    calculate_next_trigger_at,
)
from app.cwr.procedures.store.loader import ProcedureLoader


# =============================================================================
# HELPERS
# =============================================================================


def _write_proc_json(directory: Path, filename: str, data: dict) -> Path:
    """Write a procedure JSON file and return its path."""
    path = directory / filename
    path.write_text(json.dumps(data))
    return path


def _minimal_proc(slug: str = "test_proc", name: str = "Test Proc", **overrides) -> dict:
    """Return a minimal valid procedure dict."""
    d = {"slug": slug, "name": name, "steps": [], **overrides}
    return d


# =============================================================================
# 1. TestCalculateNextTriggerAt
# =============================================================================


class TestCalculateNextTriggerAt:
    """Tests for the calculate_next_trigger_at() helper."""

    def test_valid_cron_returns_future_datetime(self):
        result = calculate_next_trigger_at("0 6 * * *")
        assert isinstance(result, datetime)
        assert result > datetime.utcnow()

    def test_valid_cron_with_base_time(self):
        base = datetime(2025, 1, 1, 0, 0, 0)
        result = calculate_next_trigger_at("0 6 * * *", base_time=base)
        assert result is not None
        assert result > base

    def test_empty_string_returns_none(self):
        result = calculate_next_trigger_at("")
        assert result is None

    def test_none_returns_none(self):
        result = calculate_next_trigger_at(None)
        assert result is None

    def test_invalid_expression_returns_none(self):
        result = calculate_next_trigger_at("not a cron expression")
        assert result is None


# =============================================================================
# 2. TestProcedureDefinition
# =============================================================================


class TestProcedureDefinition:
    """Tests for ProcedureDefinition.from_dict() / to_dict() and defaults."""

    def test_from_dict_minimal(self):
        data = {"name": "My Proc", "slug": "my_proc"}
        defn = ProcedureDefinition.from_dict(data)
        assert defn.name == "My Proc"
        assert defn.slug == "my_proc"
        assert defn.steps == []
        assert defn.parameters == []
        assert defn.triggers == []
        assert defn.version == "1.0.0"
        assert defn.on_error == OnErrorPolicy.FAIL

    def test_from_dict_parses_triggers(self):
        data = {
            "name": "Triggered",
            "slug": "triggered",
            "triggers": [
                {"type": "cron", "cron_expression": "0 6 * * *"},
                {"type": "event", "event_name": "sam_pull.completed"},
            ],
        }
        defn = ProcedureDefinition.from_dict(data)
        assert len(defn.triggers) == 2
        assert defn.triggers[0].type == "cron"
        assert defn.triggers[0].cron_expression == "0 6 * * *"
        assert defn.triggers[1].type == "event"
        assert defn.triggers[1].event_name == "sam_pull.completed"

    def test_to_dict_from_dict_roundtrip(self):
        original = ProcedureDefinition(
            name="Roundtrip",
            slug="roundtrip",
            steps=[
                StepDefinition(name="s1", function="search_assets", params={"query": "test"}),
            ],
            description="A test procedure",
        )
        d = original.to_dict()
        restored = ProcedureDefinition.from_dict(d)
        assert restored.slug == original.slug
        assert restored.name == original.name
        assert len(restored.steps) == 1
        assert restored.steps[0].name == "s1"
        assert restored.steps[0].function == "search_assets"

    def test_is_system_defaults_true_for_system_source(self):
        data = {"name": "Sys", "slug": "sys"}
        defn = ProcedureDefinition.from_dict(data, source_type="system")
        assert defn.is_system is True

    def test_is_system_defaults_false_for_user_source(self):
        data = {"name": "User", "slug": "user"}
        defn = ProcedureDefinition.from_dict(data, source_type="user")
        assert defn.is_system is False


# =============================================================================
# 3. TestProcedureLoader
# =============================================================================


class TestProcedureLoader:
    """Tests for ProcedureLoader filesystem scanning and JSON parsing."""

    # -------------------------------------------------------------------------
    # discover_all / reload
    # -------------------------------------------------------------------------

    def test_discover_finds_json_files(self, tmp_path):
        _write_proc_json(tmp_path, "proc_a.json", _minimal_proc("a", "Proc A"))
        _write_proc_json(tmp_path, "proc_b.json", _minimal_proc("b", "Proc B"))
        loader = ProcedureLoader(additional_paths=[str(tmp_path)])
        with patch.object(loader, "_get_definition_paths", return_value=[tmp_path]):
            defs = loader.discover_all()
        assert len(defs) == 2
        assert "a" in defs
        assert "b" in defs

    def test_discover_ignores_non_json(self, tmp_path):
        _write_proc_json(tmp_path, "proc.json", _minimal_proc("a"))
        (tmp_path / "notes.txt").write_text("not a procedure")
        (tmp_path / "config.yaml").write_text("key: value")
        loader = ProcedureLoader(additional_paths=[str(tmp_path)])
        with patch.object(loader, "_get_definition_paths", return_value=[tmp_path]):
            defs = loader.discover_all()
        assert len(defs) == 1

    def test_discover_empty_directory(self, tmp_path):
        loader = ProcedureLoader(additional_paths=[str(tmp_path)])
        with patch.object(loader, "_get_definition_paths", return_value=[tmp_path]):
            defs = loader.discover_all()
        assert len(defs) == 0

    def test_discover_duplicate_slugs_last_wins(self, tmp_path):
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()
        _write_proc_json(dir1, "proc.json", _minimal_proc("dup", "First"))
        _write_proc_json(dir2, "proc.json", _minimal_proc("dup", "Second"))
        loader = ProcedureLoader(additional_paths=[str(dir1), str(dir2)])
        with patch.object(loader, "_get_definition_paths", return_value=[dir1, dir2]):
            defs = loader.discover_all()
        assert len(defs) == 1
        assert defs["dup"].name == "Second"

    def test_reload_picks_up_new_files(self, tmp_path):
        _write_proc_json(tmp_path, "a.json", _minimal_proc("a"))
        loader = ProcedureLoader(additional_paths=[str(tmp_path)])
        with patch.object(loader, "_get_definition_paths", return_value=[tmp_path]):
            defs = loader.discover_all()
            assert len(defs) == 1

            # Add a new file
            _write_proc_json(tmp_path, "b.json", _minimal_proc("b"))
            defs = loader.reload()
            assert len(defs) == 2

    # -------------------------------------------------------------------------
    # load_json
    # -------------------------------------------------------------------------

    def test_load_json_valid_minimal(self, tmp_path):
        path = _write_proc_json(tmp_path, "proc.json", _minimal_proc("test"))
        loader = ProcedureLoader()
        defn = loader.load_json(path)
        assert defn is not None
        assert defn.slug == "test"
        assert defn.source_type == "system"
        assert defn.source_path == str(path)

    def test_load_json_malformed(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not valid json!!}")
        loader = ProcedureLoader()
        assert loader.load_json(path) is None

    def test_load_json_empty_object(self, tmp_path):
        path = _write_proc_json(tmp_path, "empty.json", {})
        loader = ProcedureLoader()
        assert loader.load_json(path) is None

    def test_load_json_missing_name(self, tmp_path):
        path = _write_proc_json(tmp_path, "no_name.json", {"slug": "test"})
        loader = ProcedureLoader()
        assert loader.load_json(path) is None

    def test_load_json_missing_slug(self, tmp_path):
        path = _write_proc_json(tmp_path, "no_slug.json", {"name": "Test"})
        loader = ProcedureLoader()
        assert loader.load_json(path) is None

    def test_load_json_with_triggers(self, tmp_path):
        data = _minimal_proc("cron_proc", triggers=[
            {"type": "cron", "cron_expression": "0 6 * * *"},
            {"type": "event", "event_name": "extraction.completed"},
        ])
        path = _write_proc_json(tmp_path, "cron.json", data)
        loader = ProcedureLoader()
        defn = loader.load_json(path)
        assert defn is not None
        assert len(defn.triggers) == 2
        assert defn.triggers[0].cron_expression == "0 6 * * *"
        assert defn.triggers[1].event_name == "extraction.completed"

    def test_load_json_with_branching_steps(self, tmp_path):
        data = _minimal_proc("branched", steps=[
            {
                "name": "branch_step",
                "function": "if_branch",
                "params": {"condition": "{{ steps.s1.count > 0 }}"},
                "branches": {
                    "then": [{"name": "do_a", "function": "log", "params": {"message": "yes"}}],
                    "else": [{"name": "do_b", "function": "log", "params": {"message": "no"}}],
                },
            }
        ])
        path = _write_proc_json(tmp_path, "branched.json", data)
        loader = ProcedureLoader()
        defn = loader.load_json(path)
        assert defn is not None
        assert defn.steps[0].branches is not None
        assert "then" in defn.steps[0].branches
        assert "else" in defn.steps[0].branches
        assert defn.steps[0].branches["then"][0].name == "do_a"

    # -------------------------------------------------------------------------
    # get / list_all (lazy loading)
    # -------------------------------------------------------------------------

    def test_get_lazy_loads(self, tmp_path):
        _write_proc_json(tmp_path, "proc.json", _minimal_proc("lazy"))
        loader = ProcedureLoader(additional_paths=[str(tmp_path)])
        with patch.object(loader, "_get_definition_paths", return_value=[tmp_path]):
            # _definitions should be empty before first call
            assert len(loader._definitions) == 0
            result = loader.get("lazy")
            assert result is not None
            assert result.slug == "lazy"

    def test_get_returns_none_for_unknown(self, tmp_path):
        _write_proc_json(tmp_path, "proc.json", _minimal_proc("known"))
        loader = ProcedureLoader(additional_paths=[str(tmp_path)])
        with patch.object(loader, "_get_definition_paths", return_value=[tmp_path]):
            result = loader.get("unknown_slug")
            assert result is None

    def test_list_all_lazy_loads(self, tmp_path):
        _write_proc_json(tmp_path, "a.json", _minimal_proc("a"))
        _write_proc_json(tmp_path, "b.json", _minimal_proc("b"))
        loader = ProcedureLoader(additional_paths=[str(tmp_path)])
        with patch.object(loader, "_get_definition_paths", return_value=[tmp_path]):
            assert len(loader._definitions) == 0
            all_defs = loader.list_all()
            assert len(all_defs) == 2

    # -------------------------------------------------------------------------
    # render_params
    # -------------------------------------------------------------------------

    def test_render_params_jinja_substitution(self):
        loader = ProcedureLoader()
        result = loader.render_params(
            {"msg": "Hello {{ name }}"},
            {"name": "World"},
        )
        assert result["msg"] == "Hello World"

    def test_render_params_non_template_passthrough(self):
        loader = ProcedureLoader()
        result = loader.render_params(
            {"msg": "no templates here", "count": 42},
            {"name": "unused"},
        )
        assert result["msg"] == "no templates here"
        assert result["count"] == 42


# =============================================================================
# 4. TestProcedureDiscovery
# =============================================================================


class TestProcedureDiscovery:
    """Tests for ProcedureDiscoveryService.discover_and_register()."""

    ORG_ID = uuid.uuid4()

    def _make_mock_session(self, scalar_results=None):
        """Create a mock async session with pre-programmed query results.

        scalar_results: list of values that session.execute().scalar_one_or_none()
                        will return in sequence (one per definition query).
                        After those, one more call returns the stale-query result.
        """
        session = AsyncMock()
        session.add = MagicMock()
        session.delete = AsyncMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        return session

    def _make_db_procedure(self, slug, definition_dict=None, source_path=None, is_system=True):
        """Create a mock Procedure ORM object."""
        proc = MagicMock()
        proc.id = uuid.uuid4()
        proc.slug = slug
        proc.name = f"Proc {slug}"
        proc.definition = definition_dict or {}
        proc.source_path = source_path
        proc.source_type = "system"
        proc.is_system = is_system
        proc.version = 1
        proc.description = ""
        proc.updated_at = datetime.utcnow()
        return proc

    # -------------------------------------------------------------------------
    # Registration
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_new_definition_registers(self):
        """New definition with no DB record -> session.add called, registered=1."""
        defn = ProcedureDefinition.from_dict(
            _minimal_proc("new_proc"), source_type="system"
        )

        session = self._make_mock_session()
        # First execute: lookup for "new_proc" -> None
        mock_result_1 = MagicMock()
        mock_result_1.scalar_one_or_none.return_value = None
        # Second execute: stale query -> empty list
        mock_result_2 = MagicMock()
        mock_result_2.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(side_effect=[mock_result_1, mock_result_2])

        service = ProcedureDiscoveryService()
        with patch("app.cwr.procedures.store.discovery.procedure_loader") as mock_loader:
            mock_loader.discover_all.return_value = {"new_proc": defn}
            results = await service.discover_and_register(session, self.ORG_ID)

        assert results["registered"] == 1
        assert results["updated"] == 0
        assert results["unchanged"] == 0
        session.add.assert_called()

    @pytest.mark.asyncio
    async def test_changed_definition_updates(self):
        """Changed definition -> DB record attributes updated, updated=1."""
        defn = ProcedureDefinition.from_dict(
            _minimal_proc("changed", description="new desc"), source_type="system"
        )
        existing = self._make_db_procedure("changed", definition_dict={"different": True})

        session = self._make_mock_session()
        mock_result_1 = MagicMock()
        mock_result_1.scalar_one_or_none.return_value = existing
        mock_result_2 = MagicMock()
        mock_result_2.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(side_effect=[mock_result_1, mock_result_2])

        service = ProcedureDiscoveryService()
        with patch("app.cwr.procedures.store.discovery.procedure_loader") as mock_loader:
            mock_loader.discover_all.return_value = {"changed": defn}
            results = await service.discover_and_register(session, self.ORG_ID)

        assert results["updated"] == 1
        assert results["registered"] == 0

    @pytest.mark.asyncio
    async def test_unchanged_definition_no_mutation(self):
        """Unchanged definition -> no mutation, unchanged=1."""
        defn = ProcedureDefinition.from_dict(
            _minimal_proc("same"), source_type="system"
        )
        existing = self._make_db_procedure(
            "same",
            definition_dict=defn.to_dict(),
            source_path=defn.source_path,
            is_system=True,
        )

        session = self._make_mock_session()
        mock_result_1 = MagicMock()
        mock_result_1.scalar_one_or_none.return_value = existing
        mock_result_2 = MagicMock()
        mock_result_2.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(side_effect=[mock_result_1, mock_result_2])

        service = ProcedureDiscoveryService()
        with patch("app.cwr.procedures.store.discovery.procedure_loader") as mock_loader:
            mock_loader.discover_all.return_value = {"same": defn}
            results = await service.discover_and_register(session, self.ORG_ID)

        assert results["unchanged"] == 1
        assert results["updated"] == 0
        assert results["registered"] == 0

    @pytest.mark.asyncio
    async def test_is_system_mismatch_reconciled(self):
        """is_system flag mismatch -> reconciled, updated=1."""
        defn = ProcedureDefinition.from_dict(
            _minimal_proc("flag_fix"), source_type="system"
        )
        existing = self._make_db_procedure(
            "flag_fix",
            definition_dict=defn.to_dict(),
            source_path=defn.source_path,
            is_system=False,  # mismatch
        )

        session = self._make_mock_session()
        mock_result_1 = MagicMock()
        mock_result_1.scalar_one_or_none.return_value = existing
        mock_result_2 = MagicMock()
        mock_result_2.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(side_effect=[mock_result_1, mock_result_2])

        service = ProcedureDiscoveryService()
        with patch("app.cwr.procedures.store.discovery.procedure_loader") as mock_loader:
            mock_loader.discover_all.return_value = {"flag_fix": defn}
            results = await service.discover_and_register(session, self.ORG_ID)

        assert results["updated"] == 1

    # -------------------------------------------------------------------------
    # Stale cleanup (the bug scenario)
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_stale_slug_file_deleted_is_removed(self):
        """Slug not discovered + file deleted from disk -> session.delete called."""
        stale = self._make_db_procedure("gone", source_path="/tmp/gone.json")

        session = self._make_mock_session()
        # No definitions discovered
        mock_result_stale = MagicMock()
        mock_result_stale.scalars.return_value.all.return_value = [stale]
        session.execute = AsyncMock(side_effect=[mock_result_stale])

        service = ProcedureDiscoveryService()
        with patch("app.cwr.procedures.store.discovery.procedure_loader") as mock_loader, \
             patch("app.cwr.procedures.store.discovery.os.path.exists", return_value=False):
            mock_loader.discover_all.return_value = {}
            results = await service.discover_and_register(session, self.ORG_ID)

        assert results["removed"] == 1
        session.delete.assert_called_once_with(stale)

    @pytest.mark.asyncio
    async def test_stale_slug_no_source_path_is_removed(self):
        """Slug not discovered + no source_path -> session.delete called."""
        stale = self._make_db_procedure("orphan", source_path=None)

        session = self._make_mock_session()
        mock_result_stale = MagicMock()
        mock_result_stale.scalars.return_value.all.return_value = [stale]
        session.execute = AsyncMock(side_effect=[mock_result_stale])

        service = ProcedureDiscoveryService()
        with patch("app.cwr.procedures.store.discovery.procedure_loader") as mock_loader:
            mock_loader.discover_all.return_value = {}
            results = await service.discover_and_register(session, self.ORG_ID)

        assert results["removed"] == 1
        session.delete.assert_called_once_with(stale)

    @pytest.mark.asyncio
    async def test_stale_slug_file_still_exists_not_deleted(self):
        """Slug not discovered but file still on disk -> NOT deleted."""
        stale = self._make_db_procedure("still_there", source_path="/tmp/still_there.json")

        session = self._make_mock_session()
        mock_result_stale = MagicMock()
        mock_result_stale.scalars.return_value.all.return_value = [stale]
        session.execute = AsyncMock(side_effect=[mock_result_stale])

        service = ProcedureDiscoveryService()
        with patch("app.cwr.procedures.store.discovery.procedure_loader") as mock_loader, \
             patch("app.cwr.procedures.store.discovery.os.path.exists", return_value=True):
            mock_loader.discover_all.return_value = {}
            results = await service.discover_and_register(session, self.ORG_ID)

        assert results["removed"] == 0
        session.delete.assert_not_called()

    # -------------------------------------------------------------------------
    # Triggers
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_new_procedure_with_cron_trigger(self):
        """New procedure with cron trigger -> trigger added with next_trigger_at set."""
        defn = ProcedureDefinition.from_dict(
            _minimal_proc("cron_proc", triggers=[
                {"type": "cron", "cron_expression": "0 6 * * *"},
            ]),
            source_type="system",
        )

        session = self._make_mock_session()
        mock_result_1 = MagicMock()
        mock_result_1.scalar_one_or_none.return_value = None
        mock_result_stale = MagicMock()
        mock_result_stale.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(side_effect=[mock_result_1, mock_result_stale])

        service = ProcedureDiscoveryService()
        with patch("app.cwr.procedures.store.discovery.procedure_loader") as mock_loader:
            mock_loader.discover_all.return_value = {"cron_proc": defn}
            results = await service.discover_and_register(session, self.ORG_ID)

        assert results["registered"] == 1
        # session.add called for procedure + trigger
        add_calls = session.add.call_args_list
        assert len(add_calls) >= 2
        # The trigger object should have next_trigger_at set
        trigger_obj = add_calls[-1][0][0]
        assert trigger_obj.trigger_type == "cron"
        assert trigger_obj.next_trigger_at is not None

    @pytest.mark.asyncio
    async def test_new_procedure_with_event_trigger(self):
        """New procedure with event trigger -> trigger added, next_trigger_at is None."""
        defn = ProcedureDefinition.from_dict(
            _minimal_proc("event_proc", triggers=[
                {"type": "event", "event_name": "sam_pull.completed"},
            ]),
            source_type="system",
        )

        session = self._make_mock_session()
        mock_result_1 = MagicMock()
        mock_result_1.scalar_one_or_none.return_value = None
        mock_result_stale = MagicMock()
        mock_result_stale.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(side_effect=[mock_result_1, mock_result_stale])

        service = ProcedureDiscoveryService()
        with patch("app.cwr.procedures.store.discovery.procedure_loader") as mock_loader:
            mock_loader.discover_all.return_value = {"event_proc": defn}
            results = await service.discover_and_register(session, self.ORG_ID)

        assert results["registered"] == 1
        add_calls = session.add.call_args_list
        trigger_obj = add_calls[-1][0][0]
        assert trigger_obj.trigger_type == "event"
        assert trigger_obj.next_trigger_at is None

    # -------------------------------------------------------------------------
    # Error resilience
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_error_on_one_procedure_does_not_block_others(self):
        """Exception on one procedure -> other procedures still register."""
        defn_good = ProcedureDefinition.from_dict(
            _minimal_proc("good_proc"), source_type="system"
        )
        defn_bad = ProcedureDefinition.from_dict(
            _minimal_proc("bad_proc"), source_type="system"
        )

        session = self._make_mock_session()
        # First execute (for whichever proc comes first): raise error
        mock_result_bad = MagicMock()
        mock_result_bad.scalar_one_or_none.side_effect = RuntimeError("DB exploded")
        # Second execute: success (no existing)
        mock_result_good = MagicMock()
        mock_result_good.scalar_one_or_none.return_value = None
        # Stale query
        mock_result_stale = MagicMock()
        mock_result_stale.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(side_effect=[mock_result_bad, mock_result_good, mock_result_stale])

        service = ProcedureDiscoveryService()
        with patch("app.cwr.procedures.store.discovery.procedure_loader") as mock_loader:
            mock_loader.discover_all.return_value = {"bad_proc": defn_bad, "good_proc": defn_good}
            results = await service.discover_and_register(session, self.ORG_ID)

        assert results["registered"] == 1
        assert len(results["errors"]) == 1

    @pytest.mark.asyncio
    async def test_results_dict_has_expected_keys(self):
        """Return dict has all expected keys."""
        session = self._make_mock_session()
        mock_result_stale = MagicMock()
        mock_result_stale.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(side_effect=[mock_result_stale])

        service = ProcedureDiscoveryService()
        with patch("app.cwr.procedures.store.discovery.procedure_loader") as mock_loader:
            mock_loader.discover_all.return_value = {}
            results = await service.discover_and_register(session, self.ORG_ID)

        assert set(results.keys()) == {"registered", "updated", "unchanged", "removed", "errors"}


# =============================================================================
# 5. TestCascadeDeletion
# =============================================================================


class TestCascadeDeletion:
    """
    Verifies ORM relationship/FK configuration that was the bug site.

    Inspects SQLAlchemy model metadata directly — no DB needed.
    """

    def test_procedure_triggers_has_passive_deletes(self):
        from app.core.database.procedures import Procedure
        rel = Procedure.triggers.property
        assert rel.passive_deletes is True

    def test_procedure_triggers_has_delete_orphan_cascade(self):
        from app.core.database.procedures import Procedure
        rel = Procedure.triggers.property
        assert "delete-orphan" in str(rel.cascade)

    def test_procedure_versions_has_passive_deletes(self):
        from app.core.database.procedures import ProcedureVersion
        # versions is defined via backref on ProcedureVersion.procedure
        from app.core.database.procedures import Procedure
        rel = Procedure.versions.property
        assert rel.passive_deletes is True

    def test_procedure_versions_has_delete_orphan_cascade(self):
        from app.core.database.procedures import Procedure
        rel = Procedure.versions.property
        assert "delete-orphan" in str(rel.cascade)

    def test_procedure_version_fk_has_cascade_delete(self):
        from app.core.database.procedures import ProcedureVersion
        fk_col = ProcedureVersion.__table__.c.procedure_id
        fk = list(fk_col.foreign_keys)[0]
        assert fk.ondelete == "CASCADE"

    def test_procedure_trigger_fk_has_cascade_delete(self):
        from app.core.database.procedures import ProcedureTrigger
        fk_col = ProcedureTrigger.__table__.c.procedure_id
        fk = list(fk_col.foreign_keys)[0]
        assert fk.ondelete == "CASCADE"

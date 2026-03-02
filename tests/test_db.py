"""
Tests for src/db.py — YDB layer.

The YDB driver and session pool are fully mocked; no real YDB connection is made.
Each test injects a fake pool via db._pool to bypass module-level initialization.

Uses the Query API (ydb.QuerySessionPool / ydb.QuerySession).
"""
import sys
import os
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock, call
from contextlib import contextmanager

# Make src/ importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.delenv("YDB_ENDPOINT", raising=False)
    monkeypatch.delenv("YDB_DATABASE", raising=False)
    monkeypatch.setenv("VK_GROUP_TOKEN", "test")
    monkeypatch.setenv("VK_CONFIRMATION_TOKEN", "test")
    monkeypatch.setenv("VK_SECRET_KEY", "test_secret_key")
    monkeypatch.setenv("PLANK_TIMEZONE", "Europe/Moscow")


@pytest.fixture()
def db_module():
    """Fresh import of db module for each test."""
    import importlib
    import config
    importlib.reload(config)
    import db
    importlib.reload(db)
    # Reset module-level singletons so tests start clean
    db._driver = None
    db._pool = None
    return db


def make_result_set(rows):
    """Build a fake YDB result set with .rows attribute."""
    rs = MagicMock()
    rs.rows = rows
    return rs


def make_count_row(cnt):
    row = MagicMock()
    row.cnt = cnt
    return row


def make_context_manager_execute(result_sets_sequence):
    """
    Build a tx.execute context manager mock.

    result_sets_sequence: list of lists-of-result-sets for successive execute calls.
    Each entry is what iterating over the context manager yields (list of result sets).
    The context manager's __enter__ returns an iterator over that list.
    """
    call_index = [0]

    @contextmanager
    def _execute(query, params=None, commit_tx=False):
        idx = call_index[0]
        call_index[0] += 1
        result = result_sets_sequence[idx] if idx < len(result_sets_sequence) else []
        yield iter(result)

    return _execute


# ---------------------------------------------------------------------------
# get_today_date_str
# ---------------------------------------------------------------------------

class TestGetTodayDateStr:
    def test_returns_iso_date_string(self, db_module):
        result = db_module.get_today_date_str()
        assert len(result) == 10
        parts = result.split("-")
        assert len(parts) == 3
        assert len(parts[0]) == 4
        assert len(parts[1]) == 2
        assert len(parts[2]) == 2

    def test_uses_configured_timezone(self, db_module, monkeypatch):
        """UTC midnight should give March 1st in UTC+3."""
        fixed_utc = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)
        with patch("db.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_utc
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = db_module.get_today_date_str()
        assert result == "2026-03-01"

    def test_utc_late_night_is_next_day_in_msk(self, db_module):
        """23:00 UTC Feb 28 = 02:00 MSK Mar 1 → date string is 2026-03-01."""
        msk_tz = timezone(timedelta(hours=3))
        fixed_msk = datetime(2026, 3, 1, 2, 0, 0, tzinfo=msk_tz)

        with patch.object(db_module, "_get_tz", return_value=msk_tz), \
             patch("db.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_msk
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = db_module.get_today_date_str()

        assert result == "2026-03-01"


# ---------------------------------------------------------------------------
# mark_plank — helpers
# ---------------------------------------------------------------------------

def _make_mark_plank_pool(execute_results, raise_on_execute=None):
    """
    Build a mock QuerySessionPool for mark_plank tests.

    execute_results: list of result-set-lists for successive tx.execute calls.
      Each entry is a list of result sets that the context manager yields.
    raise_on_execute: if set, tx.execute raises this exception on first call.
    """
    mock_pool = MagicMock()

    def _retry(callee):
        mock_session = MagicMock()
        mock_tx = MagicMock()
        mock_session.transaction.return_value = mock_tx

        if raise_on_execute:
            mock_tx.execute.side_effect = raise_on_execute
        else:
            mock_tx.execute = make_context_manager_execute(execute_results)

        return callee(mock_session)

    mock_pool.retry_operation_sync.side_effect = _retry
    return mock_pool


def _no_existing_user():
    """Result for fetch-user query: user not found."""
    return [make_result_set([])]


def _existing_user(is_bot_admin=False, created_at=0):
    """Result for fetch-user query: user found."""
    row = MagicMock()
    row.is_bot_admin = is_bot_admin
    row.created_at = created_at
    return [make_result_set([row])]


def _count_result(cnt):
    """Result for check-count query."""
    return [make_result_set([make_count_row(cnt)])]


# ---------------------------------------------------------------------------
# mark_plank — first time today
# ---------------------------------------------------------------------------

class TestMarkPlankFirstToday:
    def test_returns_true_when_no_existing_record(self, db_module):
        """mark_plank returns PlankMarkResult(is_new=True) when user hasn't planked today."""
        pool = _make_mark_plank_pool([
            _no_existing_user(),   # fetch user
            [],                    # upsert user (no result)
            _count_result(0),      # check count → 0
            [],                    # insert plank record
        ])
        db_module._pool = pool

        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            result = db_module.mark_plank(111, "Иван Иванов", 60)

        assert result.is_new is True
        assert result.was_updated is False

    def test_returns_true_for_existing_user_first_plank(self, db_module):
        """Existing user (is_bot_admin preserved) planking first time today → is_new=True."""
        pool = _make_mark_plank_pool([
            _existing_user(is_bot_admin=True, created_at=1000),
            [],
            _count_result(0),
            [],
        ])
        db_module._pool = pool

        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            result = db_module.mark_plank(111, "Иван Иванов", None)

        assert result.is_new is True
        assert result.was_updated is False

    def test_uses_query_serializable_read_write(self, db_module):
        """Transaction must use QuerySerializableReadWrite isolation."""
        import ydb

        captured_tx_mode = []

        def _retry(callee):
            mock_session = MagicMock()
            mock_tx = MagicMock()

            def _capture_tx_mode(mode):
                captured_tx_mode.append(mode)
                return mock_tx

            mock_session.transaction.side_effect = _capture_tx_mode
            mock_tx.execute = make_context_manager_execute([
                _no_existing_user(), [], _count_result(0), [],
            ])
            return callee(mock_session)

        pool = MagicMock()
        pool.retry_operation_sync.side_effect = _retry
        db_module._pool = pool

        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            db_module.mark_plank(111, "Иван Иванов", 60)

        assert len(captured_tx_mode) == 1
        assert isinstance(captured_tx_mode[0], ydb.QuerySerializableReadWrite)

    def test_four_execute_calls_made(self, db_module):
        """Exactly 4 execute calls: fetch user, upsert user, check count, insert."""
        execute_call_count = [0]

        @contextmanager
        def _counting_execute(query, params=None, commit_tx=False):
            idx = execute_call_count[0]
            execute_call_count[0] += 1
            results = [
                _no_existing_user(),
                [],
                _count_result(0),
                [],
            ]
            yield iter(results[idx] if idx < len(results) else [])

        def _retry(callee):
            mock_session = MagicMock()
            mock_tx = MagicMock()
            mock_session.transaction.return_value = mock_tx
            mock_tx.execute = _counting_execute
            return callee(mock_session)

        pool = MagicMock()
        pool.retry_operation_sync.side_effect = _retry
        db_module._pool = pool

        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            db_module.mark_plank(111, "Иван Иванов", 60)

        assert execute_call_count[0] == 4

    def test_commit_tx_true_on_insert(self, db_module):
        """The final insert execute call must have commit_tx=True."""
        commit_tx_values = []

        @contextmanager
        def _tracking_execute(query, params=None, commit_tx=False):
            commit_tx_values.append(commit_tx)
            idx = len(commit_tx_values) - 1
            results = [_no_existing_user(), [], _count_result(0), []]
            yield iter(results[idx] if idx < len(results) else [])

        def _retry(callee):
            mock_session = MagicMock()
            mock_tx = MagicMock()
            mock_session.transaction.return_value = mock_tx
            mock_tx.execute = _tracking_execute
            return callee(mock_session)

        pool = MagicMock()
        pool.retry_operation_sync.side_effect = _retry
        db_module._pool = pool

        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            db_module.mark_plank(111, "Иван Иванов", 60)

        # First 3 calls: commit_tx=False; last call: commit_tx=True
        assert commit_tx_values == [False, False, False, True]


# ---------------------------------------------------------------------------
# mark_plank — duplicate (already done today)
# ---------------------------------------------------------------------------

class TestMarkPlankDuplicate:
    def test_returns_false_when_record_exists_no_seconds(self, db_module):
        """mark_plank returns is_new=False, was_updated=False when already done and no seconds given."""
        pool = _make_mark_plank_pool([
            _no_existing_user(),
            [],
            _count_result(1),   # count=1 → duplicate
        ])
        db_module._pool = pool

        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            result = db_module.mark_plank(111, "Иван Иванов", None)

        assert result.is_new is False
        assert result.was_updated is False

    def test_no_insert_on_duplicate_no_seconds(self, db_module):
        """When duplicate detected and no seconds given, only 3 execute calls (no insert, no update)."""
        execute_call_count = [0]

        @contextmanager
        def _counting_execute(query, params=None, commit_tx=False):
            idx = execute_call_count[0]
            execute_call_count[0] += 1
            results = [_no_existing_user(), [], _count_result(1)]
            yield iter(results[idx] if idx < len(results) else [])

        def _retry(callee):
            mock_session = MagicMock()
            mock_tx = MagicMock()
            mock_session.transaction.return_value = mock_tx
            mock_tx.execute = _counting_execute
            return callee(mock_session)

        pool = MagicMock()
        pool.retry_operation_sync.side_effect = _retry
        db_module._pool = pool

        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            db_module.mark_plank(111, "Иван Иванов", None)

        assert execute_call_count[0] == 3

    def test_commit_called_on_duplicate_no_seconds(self, db_module):
        """tx.commit() is called explicitly when duplicate detected and no seconds given."""
        committed = [False]

        def _retry(callee):
            mock_session = MagicMock()
            mock_tx = MagicMock()
            mock_session.transaction.return_value = mock_tx
            mock_tx.execute = make_context_manager_execute([
                _no_existing_user(), [], _count_result(1),
            ])

            def _commit():
                committed[0] = True

            mock_tx.commit.side_effect = _commit
            return callee(mock_session)

        pool = MagicMock()
        pool.retry_operation_sync.side_effect = _retry
        db_module._pool = pool

        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            db_module.mark_plank(111, "Иван Иванов", None)  # no seconds → explicit tx.commit()

        assert committed[0] is True


# ---------------------------------------------------------------------------
# mark_plank — update (already done, new seconds provided)
# ---------------------------------------------------------------------------

class TestMarkPlankUpdate:
    def test_returns_was_updated_true_when_record_exists_with_seconds(self, db_module):
        """mark_plank returns was_updated=True when already done and new seconds given."""
        pool = _make_mark_plank_pool([
            _no_existing_user(),
            [],
            _count_result(1),   # count=1 → duplicate
            [],                  # update query
        ])
        db_module._pool = pool

        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            result = db_module.mark_plank(111, "Иван Иванов", 120)

        assert result.is_new is False
        assert result.was_updated is True

    def test_four_execute_calls_on_update(self, db_module):
        """When updating, 4 execute calls: fetch user, upsert user, check count, update."""
        execute_call_count = [0]

        @contextmanager
        def _counting_execute(query, params=None, commit_tx=False):
            idx = execute_call_count[0]
            execute_call_count[0] += 1
            results = [_no_existing_user(), [], _count_result(1), []]
            yield iter(results[idx] if idx < len(results) else [])

        def _retry(callee):
            mock_session = MagicMock()
            mock_tx = MagicMock()
            mock_session.transaction.return_value = mock_tx
            mock_tx.execute = _counting_execute
            return callee(mock_session)

        pool = MagicMock()
        pool.retry_operation_sync.side_effect = _retry
        db_module._pool = pool

        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            db_module.mark_plank(111, "Иван Иванов", 120)

        assert execute_call_count[0] == 4

    def test_update_passes_correct_seconds(self, db_module):
        """The update execute call receives the new actual_seconds value."""
        captured_params = []

        @contextmanager
        def _capturing_execute(query, params=None, commit_tx=False):
            captured_params.append(params or {})
            idx = len(captured_params) - 1
            results = [_no_existing_user(), [], _count_result(1), []]
            yield iter(results[idx] if idx < len(results) else [])

        def _retry(callee):
            mock_session = MagicMock()
            mock_tx = MagicMock()
            mock_session.transaction.return_value = mock_tx
            mock_tx.execute = _capturing_execute
            return callee(mock_session)

        pool = MagicMock()
        pool.retry_operation_sync.side_effect = _retry
        db_module._pool = pool

        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            db_module.mark_plank(111, "Иван Иванов", 120)

        # 4th call (index 3) is the UPDATE
        update_params = captured_params[3]
        assert "$actual_seconds" in update_params
        # actual_seconds is passed as a tuple (value, type)
        assert update_params["$actual_seconds"][0] == 120

    def test_update_commit_tx_true(self, db_module):
        """The update execute call uses commit_tx=True."""
        commit_tx_values = []

        @contextmanager
        def _tracking_execute(query, params=None, commit_tx=False):
            commit_tx_values.append(commit_tx)
            idx = len(commit_tx_values) - 1
            results = [_no_existing_user(), [], _count_result(1), []]
            yield iter(results[idx] if idx < len(results) else [])

        def _retry(callee):
            mock_session = MagicMock()
            mock_tx = MagicMock()
            mock_session.transaction.return_value = mock_tx
            mock_tx.execute = _tracking_execute
            return callee(mock_session)

        pool = MagicMock()
        pool.retry_operation_sync.side_effect = _retry
        db_module._pool = pool

        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            db_module.mark_plank(111, "Иван Иванов", 120)

        # First 3: False, False, False; 4th (update): True
        assert commit_tx_values == [False, False, False, True]


# ---------------------------------------------------------------------------
# mark_plank — error handling
# ---------------------------------------------------------------------------

class TestMarkPlankErrorHandling:
    def test_rollback_called_on_exception(self, db_module):
        """If execute raises, rollback is called and exception re-raised."""
        rolled_back = [False]

        def _retry(callee):
            mock_session = MagicMock()
            mock_tx = MagicMock()
            mock_session.transaction.return_value = mock_tx

            @contextmanager
            def _raising_execute(query, params=None, commit_tx=False):
                raise RuntimeError("YDB error")
                yield  # make it a generator

            mock_tx.execute = _raising_execute

            def _rollback():
                rolled_back[0] = True

            mock_tx.rollback.side_effect = _rollback
            return callee(mock_session)

        pool = MagicMock()
        pool.retry_operation_sync.side_effect = _retry
        db_module._pool = pool

        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            with pytest.raises(RuntimeError, match="YDB error"):
                db_module.mark_plank(111, "Иван Иванов", 60)

        assert rolled_back[0] is True


# ---------------------------------------------------------------------------
# get_stats_for_today
# ---------------------------------------------------------------------------

def _make_done_row(name, actual_seconds):
    row = MagicMock()
    row.name = name
    row.actual_seconds = actual_seconds
    return row


def _make_not_done_row(name):
    row = MagicMock()
    row.name = name
    return row


class TestGetStatsForToday:
    def _setup_pool(self, db_module, done_rows, not_done_rows):
        """
        Set up a mock pool where execute_with_retries returns result sets.
        First call → done query, second call → not_done query.
        """
        pool = MagicMock()
        call_index = [0]

        def _execute_with_retries(query, params=None):
            idx = call_index[0]
            call_index[0] += 1
            rs = MagicMock()
            if idx == 0:
                rs.rows = done_rows
            else:
                rs.rows = not_done_rows
            return [rs]

        pool.execute_with_retries.side_effect = _execute_with_retries
        db_module._pool = pool
        return pool

    def test_returns_empty_lists_when_no_data(self, db_module):
        self._setup_pool(db_module, [], [])

        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            done, not_done = db_module.get_stats_for_today()

        assert done == []
        assert not_done == []

    def test_formats_done_with_seconds(self, db_module):
        self._setup_pool(db_module, [_make_done_row("Иван Иванов", 60)], [])

        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            done, not_done = db_module.get_stats_for_today()

        assert done == ["Иван Иванов (60)"]
        assert not_done == []

    def test_formats_done_without_seconds(self, db_module):
        self._setup_pool(db_module, [_make_done_row("Мария Смирнова", None)], [])

        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            done, not_done = db_module.get_stats_for_today()

        assert done == ["Мария Смирнова"]

    def test_returns_not_done_list(self, db_module):
        self._setup_pool(db_module, [], [
            _make_not_done_row("Пётр Петров"),
            _make_not_done_row("Анна Кузнецова"),
        ])

        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            done, not_done = db_module.get_stats_for_today()

        assert not_done == ["Пётр Петров", "Анна Кузнецова"]

    def test_mixed_done_and_not_done(self, db_module):
        self._setup_pool(db_module, [
            _make_done_row("Иван Иванов", 90),
            _make_done_row("Мария Смирнова", None),
        ], [_make_not_done_row("Пётр Петров")])

        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            done, not_done = db_module.get_stats_for_today()

        assert "Иван Иванов (90)" in done
        assert "Мария Смирнова" in done
        assert not_done == ["Пётр Петров"]

    def test_calls_execute_with_retries_twice(self, db_module):
        """get_stats_for_today makes exactly 2 execute_with_retries calls."""
        pool = self._setup_pool(db_module, [], [])

        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            db_module.get_stats_for_today()

        assert pool.execute_with_retries.call_count == 2

    def test_passes_plank_date_param(self, db_module):
        """Both execute_with_retries calls include $plank_date parameter."""
        pool = self._setup_pool(db_module, [], [])

        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            db_module.get_stats_for_today()

        for c in pool.execute_with_retries.call_args_list:
            params = c[0][1] if len(c[0]) > 1 else c[1].get("params", c[0][1] if len(c[0]) > 1 else {})
            # params is the second positional arg
            assert "$plank_date" in c[0][1]
            assert c[0][1]["$plank_date"] == "2026-03-01"


# ---------------------------------------------------------------------------
# ensure_user
# ---------------------------------------------------------------------------

def _make_ensure_user_pool(execute_results, raise_on_execute=None):
    """Build a mock pool for ensure_user tests (same shape as mark_plank pool)."""
    mock_pool = MagicMock()

    def _retry(callee):
        mock_session = MagicMock()
        mock_tx = MagicMock()
        mock_session.transaction.return_value = mock_tx

        if raise_on_execute:
            mock_tx.execute.side_effect = raise_on_execute
        else:
            mock_tx.execute = make_context_manager_execute(execute_results)

        return callee(mock_session)

    mock_pool.retry_operation_sync.side_effect = _retry
    return mock_pool


class TestEnsureUser:
    def test_new_user_two_execute_calls(self, db_module):
        """ensure_user for a new user makes exactly 2 execute calls: read + upsert."""
        execute_call_count = [0]

        @contextmanager
        def _counting_execute(query, params=None, commit_tx=False):
            idx = execute_call_count[0]
            execute_call_count[0] += 1
            results = [_no_existing_user(), []]
            yield iter(results[idx] if idx < len(results) else [])

        def _retry(callee):
            mock_session = MagicMock()
            mock_tx = MagicMock()
            mock_session.transaction.return_value = mock_tx
            mock_tx.execute = _counting_execute
            return callee(mock_session)

        pool = MagicMock()
        pool.retry_operation_sync.side_effect = _retry
        db_module._pool = pool

        db_module.ensure_user(111, "Иван Иванов")

        assert execute_call_count[0] == 2

    def test_existing_user_two_execute_calls(self, db_module):
        """ensure_user for an existing user also makes exactly 2 execute calls."""
        execute_call_count = [0]

        @contextmanager
        def _counting_execute(query, params=None, commit_tx=False):
            idx = execute_call_count[0]
            execute_call_count[0] += 1
            results = [_existing_user(is_bot_admin=True, created_at=9999), []]
            yield iter(results[idx] if idx < len(results) else [])

        def _retry(callee):
            mock_session = MagicMock()
            mock_tx = MagicMock()
            mock_session.transaction.return_value = mock_tx
            mock_tx.execute = _counting_execute
            return callee(mock_session)

        pool = MagicMock()
        pool.retry_operation_sync.side_effect = _retry
        db_module._pool = pool

        db_module.ensure_user(111, "Иван Иванов")

        assert execute_call_count[0] == 2

    def test_existing_user_preserves_is_bot_admin(self, db_module):
        """ensure_user preserves is_bot_admin=True from existing row."""
        captured_params = []

        @contextmanager
        def _capturing_execute(query, params=None, commit_tx=False):
            captured_params.append(params or {})
            idx = len(captured_params) - 1
            results = [_existing_user(is_bot_admin=True, created_at=1234), []]
            yield iter(results[idx] if idx < len(results) else [])

        def _retry(callee):
            mock_session = MagicMock()
            mock_tx = MagicMock()
            mock_session.transaction.return_value = mock_tx
            mock_tx.execute = _capturing_execute
            return callee(mock_session)

        pool = MagicMock()
        pool.retry_operation_sync.side_effect = _retry
        db_module._pool = pool

        db_module.ensure_user(111, "Иван Иванов")

        # 2nd call (index 1) is the UPSERT
        upsert_params = captured_params[1]
        assert upsert_params["$is_bot_admin"] is True

    def test_new_user_is_bot_admin_defaults_false(self, db_module):
        """ensure_user sets is_bot_admin=False for a new user."""
        captured_params = []

        @contextmanager
        def _capturing_execute(query, params=None, commit_tx=False):
            captured_params.append(params or {})
            idx = len(captured_params) - 1
            results = [_no_existing_user(), []]
            yield iter(results[idx] if idx < len(results) else [])

        def _retry(callee):
            mock_session = MagicMock()
            mock_tx = MagicMock()
            mock_session.transaction.return_value = mock_tx
            mock_tx.execute = _capturing_execute
            return callee(mock_session)

        pool = MagicMock()
        pool.retry_operation_sync.side_effect = _retry
        db_module._pool = pool

        db_module.ensure_user(111, "Иван Иванов")

        upsert_params = captured_params[1]
        assert upsert_params["$is_bot_admin"] is False

    def test_upsert_commit_tx_true(self, db_module):
        """The upsert execute call (2nd) must have commit_tx=True."""
        commit_tx_values = []

        @contextmanager
        def _tracking_execute(query, params=None, commit_tx=False):
            commit_tx_values.append(commit_tx)
            idx = len(commit_tx_values) - 1
            results = [_no_existing_user(), []]
            yield iter(results[idx] if idx < len(results) else [])

        def _retry(callee):
            mock_session = MagicMock()
            mock_tx = MagicMock()
            mock_session.transaction.return_value = mock_tx
            mock_tx.execute = _tracking_execute
            return callee(mock_session)

        pool = MagicMock()
        pool.retry_operation_sync.side_effect = _retry
        db_module._pool = pool

        db_module.ensure_user(111, "Иван Иванов")

        assert commit_tx_values == [False, True]

    def test_uses_serializable_read_write_transaction(self, db_module):
        """ensure_user uses QuerySerializableReadWrite isolation."""
        import ydb

        captured_tx_mode = []

        def _retry(callee):
            mock_session = MagicMock()
            mock_tx = MagicMock()

            def _capture_tx_mode(mode):
                captured_tx_mode.append(mode)
                return mock_tx

            mock_session.transaction.side_effect = _capture_tx_mode
            mock_tx.execute = make_context_manager_execute([_no_existing_user(), []])
            return callee(mock_session)

        pool = MagicMock()
        pool.retry_operation_sync.side_effect = _retry
        db_module._pool = pool

        db_module.ensure_user(111, "Иван Иванов")

        assert len(captured_tx_mode) == 1
        assert isinstance(captured_tx_mode[0], ydb.QuerySerializableReadWrite)

    def test_upsert_passes_correct_user_id_and_name(self, db_module):
        """ensure_user passes user_id and name to the upsert call."""
        captured_params = []

        @contextmanager
        def _capturing_execute(query, params=None, commit_tx=False):
            captured_params.append(params or {})
            idx = len(captured_params) - 1
            results = [_no_existing_user(), []]
            yield iter(results[idx] if idx < len(results) else [])

        def _retry(callee):
            mock_session = MagicMock()
            mock_tx = MagicMock()
            mock_session.transaction.return_value = mock_tx
            mock_tx.execute = _capturing_execute
            return callee(mock_session)

        pool = MagicMock()
        pool.retry_operation_sync.side_effect = _retry
        db_module._pool = pool

        db_module.ensure_user(42, "Мария Смирнова")

        upsert_params = captured_params[1]
        assert upsert_params["$user_id"] == 42
        assert upsert_params["$name"] == "Мария Смирнова"

    def test_rollback_called_on_exception(self, db_module):
        """If execute raises, rollback is called and exception re-raised."""
        rolled_back = [False]

        def _retry(callee):
            mock_session = MagicMock()
            mock_tx = MagicMock()
            mock_session.transaction.return_value = mock_tx

            @contextmanager
            def _raising_execute(query, params=None, commit_tx=False):
                raise RuntimeError("YDB error")
                yield

            mock_tx.execute = _raising_execute

            def _rollback():
                rolled_back[0] = True

            mock_tx.rollback.side_effect = _rollback
            return callee(mock_session)

        pool = MagicMock()
        pool.retry_operation_sync.side_effect = _retry
        db_module._pool = pool

        with pytest.raises(RuntimeError, match="YDB error"):
            db_module.ensure_user(111, "Иван Иванов")

        assert rolled_back[0] is True


# ---------------------------------------------------------------------------
# save_message
# ---------------------------------------------------------------------------

class TestSaveMessage:
    def _setup_pool(self, db_module):
        pool = MagicMock()
        pool.execute_with_retries.return_value = [MagicMock()]
        db_module._pool = pool
        return pool

    def test_calls_execute_with_retries_once(self, db_module):
        pool = self._setup_pool(db_module)
        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            db_module.save_message("msg123", 111, "Иван Иванов", "Привет всем")
        assert pool.execute_with_retries.call_count == 1

    def test_passes_correct_params(self, db_module):
        pool = self._setup_pool(db_module)
        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            db_module.save_message("msg999", 42, "Мария Смирнова", "Привет")
        params = pool.execute_with_retries.call_args[0][1]
        assert params["$message_id"] == "msg999"
        assert params["$user_id"] == 42
        assert params["$user_name"] == "Мария Смирнова"
        assert params["$msg_date"] == "2026-03-01"
        assert params["$text"] == "Привет"

    def test_created_at_is_timestamp_tuple(self, db_module):
        """$created_at must be a (value, Timestamp) tuple for YDB SDK."""
        import ydb
        pool = self._setup_pool(db_module)
        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            db_module.save_message("msg1", 1, "Тест", "текст")
        params = pool.execute_with_retries.call_args[0][1]
        created_at = params["$created_at"]
        assert isinstance(created_at, tuple)
        assert created_at[1] == ydb.PrimitiveType.Timestamp

    def test_uses_upsert_query(self, db_module):
        """Query must be an UPSERT (idempotent)."""
        pool = self._setup_pool(db_module)
        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            db_module.save_message("msg1", 1, "Тест", "текст")
        query = pool.execute_with_retries.call_args[0][0]
        assert "UPSERT" in query.upper()


# ---------------------------------------------------------------------------
# get_messages_for_today
# ---------------------------------------------------------------------------

def _make_msg_row(user_name, text):
    row = MagicMock()
    row.user_name = user_name
    row.text = text
    return row


class TestGetMessagesForToday:
    def _setup_pool(self, db_module, rows):
        pool = MagicMock()
        rs = MagicMock()
        rs.rows = rows
        pool.execute_with_retries.return_value = [rs]
        db_module._pool = pool
        return pool

    def test_returns_empty_list_when_no_messages(self, db_module):
        self._setup_pool(db_module, [])
        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            result = db_module.get_messages_for_today()
        assert result == []

    def test_groups_messages_by_user(self, db_module):
        rows = [
            _make_msg_row("Иван Иванов", "Привет"),
            _make_msg_row("Иван Иванов", "Как дела?"),
            _make_msg_row("Мария Смирнова", "Всё хорошо"),
        ]
        self._setup_pool(db_module, rows)
        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            result = db_module.get_messages_for_today()

        result_dict = dict(result)
        assert "Иван Иванов" in result_dict
        assert "Мария Смирнова" in result_dict
        assert result_dict["Иван Иванов"] == ["Привет", "Как дела?"]
        assert result_dict["Мария Смирнова"] == ["Всё хорошо"]

    def test_sorted_by_user_name(self, db_module):
        rows = [
            _make_msg_row("Пётр Петров", "раз"),
            _make_msg_row("Анна Кузнецова", "два"),
            _make_msg_row("Иван Иванов", "три"),
        ]
        self._setup_pool(db_module, rows)
        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            result = db_module.get_messages_for_today()

        names = [name for name, _ in result]
        assert names == sorted(names)

    def test_passes_msg_date_param(self, db_module):
        pool = self._setup_pool(db_module, [])
        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            db_module.get_messages_for_today()
        params = pool.execute_with_retries.call_args[0][1]
        assert "$msg_date" in params
        assert params["$msg_date"] == "2026-03-01"

    def test_single_user_single_message(self, db_module):
        rows = [_make_msg_row("Иван Иванов", "Только я тут")]
        self._setup_pool(db_module, rows)
        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            result = db_module.get_messages_for_today()
        assert len(result) == 1
        assert result[0][0] == "Иван Иванов"
        assert result[0][1] == ["Только я тут"]

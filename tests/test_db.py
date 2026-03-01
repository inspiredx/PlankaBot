"""
Tests for src/db.py — YDB layer.

The YDB driver and session pool are fully mocked; no real YDB connection is made.
Each test injects a fake pool via db._pool to bypass _build_driver().
"""
import sys
import os
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock, call

# Make src/ importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("YDB_ENDPOINT", "grpcs://localhost:2135")
    monkeypatch.setenv("YDB_DATABASE", "/local")
    monkeypatch.setenv("VK_GROUP_TOKEN", "test")
    monkeypatch.setenv("VK_CONFIRMATION_TOKEN", "test")
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


def make_fake_pool(callee_result):
    """
    Return a mock SessionPool whose retry_operation_sync calls the provided
    callee with a mock session and returns callee_result.
    """
    mock_pool = MagicMock()

    def _retry(callee):
        mock_session = MagicMock()
        return callee(mock_session)

    mock_pool.retry_operation_sync.side_effect = _retry
    return mock_pool


def make_fake_tx(execute_side_effects=None):
    """
    Return a mock transaction.
    execute_side_effects: list of return values for successive tx.execute() calls.
    """
    mock_tx = MagicMock()
    if execute_side_effects is not None:
        mock_tx.execute.side_effect = execute_side_effects
    return mock_tx


def make_result_set(rows):
    """Build a fake YDB result set list: [result_set] where result_set.rows = rows."""
    rs = MagicMock()
    rs.rows = rows
    return [rs]


def make_count_row(cnt):
    row = MagicMock()
    row.cnt = cnt
    return row


# ---------------------------------------------------------------------------
# get_today_date_str
# ---------------------------------------------------------------------------

class TestGetTodayDateStr:
    def test_returns_iso_date_string(self, db_module):
        result = db_module.get_today_date_str()
        # Must be YYYY-MM-DD format
        assert len(result) == 10
        parts = result.split("-")
        assert len(parts) == 3
        assert len(parts[0]) == 4  # year
        assert len(parts[1]) == 2  # month
        assert len(parts[2]) == 2  # day

    def test_uses_configured_timezone(self, db_module, monkeypatch):
        """UTC midnight should give previous day in UTC+3."""
        # Patch datetime.now to return UTC midnight
        fixed_utc = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)  # midnight UTC = 03:00 MSK
        with patch("db.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_utc
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = db_module.get_today_date_str()
        # midnight UTC = 03:00 MSK → still March 1st in MSK
        assert result == "2026-03-01"

    def test_utc_late_night_is_next_day_in_msk(self, db_module):
        """23:00 UTC Feb 28 = 02:00 MSK Mar 1 → date string is 2026-03-01."""
        msk_tz = timezone(timedelta(hours=3))
        # The MSK-aware datetime for 23:00 UTC Feb 28 = 02:00 MSK Mar 1
        fixed_msk = datetime(2026, 3, 1, 2, 0, 0, tzinfo=msk_tz)

        # _get_tz() returns UTC+3; get_today_date_str() calls datetime.now(tz).
        # Mock datetime.now to return the MSK-offset datetime (as the real call would).
        with patch.object(db_module, "_get_tz", return_value=msk_tz), \
             patch("db.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_msk
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = db_module.get_today_date_str()

        assert result == "2026-03-01"


# ---------------------------------------------------------------------------
# mark_plank — first time today
# ---------------------------------------------------------------------------

class TestMarkPlankFirstToday:
    def test_returns_true_when_no_existing_record(self, db_module):
        """mark_plank returns True when user hasn't planked today."""
        count_result = make_result_set([make_count_row(0)])

        mock_tx = MagicMock()
        # execute calls: upsert_user, check_count, insert
        mock_tx.execute.side_effect = [
            None,               # upsert user
            count_result,       # check existing record → count=0
            None,               # insert plank record
        ]

        mock_session = MagicMock()
        mock_session.transaction.return_value = mock_tx

        mock_pool = MagicMock()
        mock_pool.retry_operation_sync.side_effect = lambda callee: callee(mock_session)

        db_module._pool = mock_pool

        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            result = db_module.mark_plank(111, "Иван Иванов", 60)

        assert result is True

    def test_commits_transaction_on_success(self, db_module):
        """Transaction is committed after successful insert."""
        count_result = make_result_set([make_count_row(0)])

        mock_tx = MagicMock()
        mock_tx.execute.side_effect = [None, count_result, None]

        mock_session = MagicMock()
        mock_session.transaction.return_value = mock_tx

        mock_pool = MagicMock()
        mock_pool.retry_operation_sync.side_effect = lambda callee: callee(mock_session)

        db_module._pool = mock_pool

        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            db_module.mark_plank(111, "Иван Иванов", None)

        mock_tx.commit.assert_called_once()
        mock_tx.rollback.assert_not_called()

    def test_uses_serializable_read_write_isolation(self, db_module):
        """Transaction must use SerializableReadWrite isolation."""
        import ydb
        count_result = make_result_set([make_count_row(0)])

        mock_tx = MagicMock()
        mock_tx.execute.side_effect = [None, count_result, None]

        mock_session = MagicMock()
        mock_session.transaction.return_value = mock_tx

        mock_pool = MagicMock()
        mock_pool.retry_operation_sync.side_effect = lambda callee: callee(mock_session)

        db_module._pool = mock_pool

        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            db_module.mark_plank(111, "Иван Иванов", 60)

        # Verify session.transaction was called with SerializableReadWrite
        call_args = mock_session.transaction.call_args
        assert isinstance(call_args[0][0], ydb.SerializableReadWrite)

    def test_three_execute_calls_made(self, db_module):
        """Exactly 3 execute calls: upsert user, check count, insert record."""
        count_result = make_result_set([make_count_row(0)])

        mock_tx = MagicMock()
        mock_tx.execute.side_effect = [None, count_result, None]

        mock_session = MagicMock()
        mock_session.transaction.return_value = mock_tx

        mock_pool = MagicMock()
        mock_pool.retry_operation_sync.side_effect = lambda callee: callee(mock_session)

        db_module._pool = mock_pool

        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            db_module.mark_plank(111, "Иван Иванов", 60)

        assert mock_tx.execute.call_count == 3


# ---------------------------------------------------------------------------
# mark_plank — duplicate (already done today)
# ---------------------------------------------------------------------------

class TestMarkPlankDuplicate:
    def test_returns_false_when_record_exists(self, db_module):
        """mark_plank returns False when user already planked today."""
        count_result = make_result_set([make_count_row(1)])

        mock_tx = MagicMock()
        mock_tx.execute.side_effect = [
            None,           # upsert user
            count_result,   # check existing record → count=1
        ]

        mock_session = MagicMock()
        mock_session.transaction.return_value = mock_tx

        mock_pool = MagicMock()
        mock_pool.retry_operation_sync.side_effect = lambda callee: callee(mock_session)

        db_module._pool = mock_pool

        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            result = db_module.mark_plank(111, "Иван Иванов", 60)

        assert result is False

    def test_no_insert_on_duplicate(self, db_module):
        """When duplicate detected, only 2 execute calls (no insert)."""
        count_result = make_result_set([make_count_row(1)])

        mock_tx = MagicMock()
        mock_tx.execute.side_effect = [None, count_result]

        mock_session = MagicMock()
        mock_session.transaction.return_value = mock_tx

        mock_pool = MagicMock()
        mock_pool.retry_operation_sync.side_effect = lambda callee: callee(mock_session)

        db_module._pool = mock_pool

        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            db_module.mark_plank(111, "Иван Иванов", 60)

        assert mock_tx.execute.call_count == 2

    def test_commits_on_duplicate(self, db_module):
        """Transaction is still committed (cleanly) on duplicate."""
        count_result = make_result_set([make_count_row(1)])

        mock_tx = MagicMock()
        mock_tx.execute.side_effect = [None, count_result]

        mock_session = MagicMock()
        mock_session.transaction.return_value = mock_tx

        mock_pool = MagicMock()
        mock_pool.retry_operation_sync.side_effect = lambda callee: callee(mock_session)

        db_module._pool = mock_pool

        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            db_module.mark_plank(111, "Иван Иванов", 60)

        mock_tx.commit.assert_called_once()


# ---------------------------------------------------------------------------
# mark_plank — error handling
# ---------------------------------------------------------------------------

class TestMarkPlankErrorHandling:
    def test_rollback_called_on_exception(self, db_module):
        """If execute raises, rollback is called and exception re-raised."""
        mock_tx = MagicMock()
        mock_tx.execute.side_effect = RuntimeError("YDB error")

        mock_session = MagicMock()
        mock_session.transaction.return_value = mock_tx

        mock_pool = MagicMock()
        mock_pool.retry_operation_sync.side_effect = lambda callee: callee(mock_session)

        db_module._pool = mock_pool

        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            with pytest.raises(RuntimeError, match="YDB error"):
                db_module.mark_plank(111, "Иван Иванов", 60)

        mock_tx.rollback.assert_called_once()


# ---------------------------------------------------------------------------
# get_stats_for_today
# ---------------------------------------------------------------------------

class TestGetStatsForToday:
    def _make_done_row(self, name, actual_seconds):
        row = MagicMock()
        row.name = name
        row.actual_seconds = actual_seconds
        return row

    def _make_not_done_row(self, name):
        row = MagicMock()
        row.name = name
        return row

    def test_returns_empty_lists_when_no_data(self, db_module):
        done_rs = make_result_set([])
        not_done_rs = make_result_set([])

        mock_tx = MagicMock()
        mock_tx.execute.side_effect = [done_rs, not_done_rs]

        mock_session = MagicMock()
        mock_session.transaction.return_value = mock_tx

        mock_pool = MagicMock()
        mock_pool.retry_operation_sync.side_effect = lambda callee: callee(mock_session)

        db_module._pool = mock_pool

        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            done, not_done = db_module.get_stats_for_today()

        assert done == []
        assert not_done == []

    def test_formats_done_with_seconds(self, db_module):
        """User with actual_seconds → 'Имя (60)'."""
        done_rs = make_result_set([self._make_done_row("Иван Иванов", 60)])
        not_done_rs = make_result_set([])

        mock_tx = MagicMock()
        mock_tx.execute.side_effect = [done_rs, not_done_rs]

        mock_session = MagicMock()
        mock_session.transaction.return_value = mock_tx

        mock_pool = MagicMock()
        mock_pool.retry_operation_sync.side_effect = lambda callee: callee(mock_session)

        db_module._pool = mock_pool

        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            done, not_done = db_module.get_stats_for_today()

        assert done == ["Иван Иванов (60)"]
        assert not_done == []

    def test_formats_done_without_seconds(self, db_module):
        """User with actual_seconds=None → just 'Имя'."""
        done_rs = make_result_set([self._make_done_row("Мария Смирнова", None)])
        not_done_rs = make_result_set([])

        mock_tx = MagicMock()
        mock_tx.execute.side_effect = [done_rs, not_done_rs]

        mock_session = MagicMock()
        mock_session.transaction.return_value = mock_tx

        mock_pool = MagicMock()
        mock_pool.retry_operation_sync.side_effect = lambda callee: callee(mock_session)

        db_module._pool = mock_pool

        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            done, not_done = db_module.get_stats_for_today()

        assert done == ["Мария Смирнова"]

    def test_returns_not_done_list(self, db_module):
        """Users not in plank_records today appear in not_done list."""
        done_rs = make_result_set([])
        not_done_rs = make_result_set([
            self._make_not_done_row("Пётр Петров"),
            self._make_not_done_row("Анна Кузнецова"),
        ])

        mock_tx = MagicMock()
        mock_tx.execute.side_effect = [done_rs, not_done_rs]

        mock_session = MagicMock()
        mock_session.transaction.return_value = mock_tx

        mock_pool = MagicMock()
        mock_pool.retry_operation_sync.side_effect = lambda callee: callee(mock_session)

        db_module._pool = mock_pool

        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            done, not_done = db_module.get_stats_for_today()

        assert not_done == ["Пётр Петров", "Анна Кузнецова"]

    def test_mixed_done_and_not_done(self, db_module):
        """Both lists populated correctly."""
        done_rs = make_result_set([
            self._make_done_row("Иван Иванов", 90),
            self._make_done_row("Мария Смирнова", None),
        ])
        not_done_rs = make_result_set([self._make_not_done_row("Пётр Петров")])

        mock_tx = MagicMock()
        mock_tx.execute.side_effect = [done_rs, not_done_rs]

        mock_session = MagicMock()
        mock_session.transaction.return_value = mock_tx

        mock_pool = MagicMock()
        mock_pool.retry_operation_sync.side_effect = lambda callee: callee(mock_session)

        db_module._pool = mock_pool

        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            done, not_done = db_module.get_stats_for_today()

        assert "Иван Иванов (90)" in done
        assert "Мария Смирнова" in done
        assert not_done == ["Пётр Петров"]

    def test_commits_transaction(self, db_module):
        """Stats query commits its read transaction."""
        done_rs = make_result_set([])
        not_done_rs = make_result_set([])

        mock_tx = MagicMock()
        mock_tx.execute.side_effect = [done_rs, not_done_rs]

        mock_session = MagicMock()
        mock_session.transaction.return_value = mock_tx

        mock_pool = MagicMock()
        mock_pool.retry_operation_sync.side_effect = lambda callee: callee(mock_session)

        db_module._pool = mock_pool

        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            db_module.get_stats_for_today()

        mock_tx.commit.assert_called_once()

    def test_rollback_on_exception(self, db_module):
        """If stats query fails, rollback is called."""
        mock_tx = MagicMock()
        mock_tx.execute.side_effect = RuntimeError("YDB error")

        mock_session = MagicMock()
        mock_session.transaction.return_value = mock_tx

        mock_pool = MagicMock()
        mock_pool.retry_operation_sync.side_effect = lambda callee: callee(mock_session)

        db_module._pool = mock_pool

        with patch.object(db_module, "get_today_date_str", return_value="2026-03-01"):
            with pytest.raises(RuntimeError):
                db_module.get_stats_for_today()

        mock_tx.rollback.assert_called_once()
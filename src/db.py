"""
YDB database layer for PlankaBot.

All writes use explicit SerializableReadWrite transactions (begin → ops → commit).
The driver and session pool are initialized once at module level to survive
warm Cloud Function invocations.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import ydb
import ydb.iam

from config import YDB_ENDPOINT, YDB_DATABASE, PLANK_TIMEZONE

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Timezone helper
# ---------------------------------------------------------------------------

def _get_tz() -> timezone:
    """Parse PLANK_TIMEZONE into a datetime.timezone offset.

    Uses zoneinfo (Python 3.9+) with a fallback to UTC+3 if unavailable.
    """
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(PLANK_TIMEZONE)
        now_utc = datetime.now(timezone.utc)
        offset = now_utc.astimezone(tz).utcoffset()
        return timezone(offset)
    except Exception:
        logger.warning("Could not resolve timezone %r, falling back to UTC+3", PLANK_TIMEZONE)
        return timezone(timedelta(hours=3))


def get_today_date_str() -> str:
    """Return today's date as ISO string (YYYY-MM-DD) in the configured timezone."""
    tz = _get_tz()
    return datetime.now(tz).date().isoformat()


# ---------------------------------------------------------------------------
# YDB driver / session pool — initialized once at module level
# ---------------------------------------------------------------------------

def _build_driver() -> ydb.Driver:
    credentials = ydb.iam.MetadataUrlCredentials()
    driver_config = ydb.DriverConfig(
        endpoint=YDB_ENDPOINT,
        database=YDB_DATABASE,
        credentials=credentials,
    )
    driver = ydb.Driver(driver_config)
    driver.wait(fail_fast=True, timeout=5)
    return driver


# Module-level singletons — populated on first real usage.
# Tests replace these with mocks before calling db functions.
_driver: Optional[ydb.Driver] = None
_pool: Optional[ydb.SessionPool] = None


def _get_pool() -> ydb.SessionPool:
    global _driver, _pool
    if _pool is None:
        _driver = _build_driver()
        _pool = ydb.SessionPool(_driver)
    return _pool


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def mark_plank(user_id: int, name: str, actual_seconds: Optional[int]) -> bool:
    """
    Record today's plank for user_id.

    Returns True if this is the first record today (success),
    False if the user already has a record for today (duplicate).

    Uses an explicit SerializableReadWrite transaction:
      1. Upsert user (create or update name + last_activity)
      2. Check for existing plank_records row for today
      3. If none, insert it
    """
    pool = _get_pool()
    today = get_today_date_str()
    now_us = int(datetime.now(timezone.utc).timestamp() * 1_000_000)

    def _callee(session: ydb.Session):
        tx = session.transaction(ydb.SerializableReadWrite())
        tx.begin()

        try:
            # Step 1: Upsert user — preserve is_bot_admin and created_at if row exists
            upsert_user_query = """
                DECLARE $user_id AS Int64;
                DECLARE $name AS Utf8;
                DECLARE $now AS Timestamp;

                UPSERT INTO users (user_id, name, is_bot_admin, last_activity, created_at)
                SELECT
                    $user_id AS user_id,
                    $name AS name,
                    COALESCE(e.is_bot_admin, false) AS is_bot_admin,
                    $now AS last_activity,
                    COALESCE(e.created_at, $now) AS created_at
                FROM (SELECT 1) AS dummy
                LEFT JOIN (SELECT is_bot_admin, created_at FROM users WHERE user_id = $user_id) AS e ON true;
            """
            tx.execute(upsert_user_query, {
                "$user_id": user_id,
                "$name": name,
                "$now": now_us,
            })

            # Step 2: Check if plank_records row exists for today
            check_query = """
                DECLARE $user_id AS Int64;
                DECLARE $plank_date AS Utf8;

                SELECT COUNT(*) AS cnt
                FROM plank_records
                WHERE user_id = $user_id AND plank_date = $plank_date;
            """
            result = tx.execute(check_query, {
                "$user_id": user_id,
                "$plank_date": today,
            })
            count = result[0].rows[0].cnt if result[0].rows else 0

            if count > 0:
                tx.commit()
                return False

            # Step 3: Insert plank record
            insert_query = """
                DECLARE $user_id AS Int64;
                DECLARE $plank_date AS Utf8;
                DECLARE $actual_seconds AS Int32?;
                DECLARE $now AS Timestamp;

                INSERT INTO plank_records (user_id, plank_date, actual_seconds, created_at)
                VALUES ($user_id, $plank_date, $actual_seconds, $now);
            """
            tx.execute(insert_query, {
                "$user_id": user_id,
                "$plank_date": today,
                "$actual_seconds": actual_seconds,
                "$now": now_us,
            })

            tx.commit()
            return True

        except Exception:
            try:
                tx.rollback()
            except Exception:
                pass
            raise

    return pool.retry_operation_sync(_callee)


def get_stats_for_today() -> tuple[list[str], list[str]]:
    """
    Return (done, not_done) lists for today.

    done: display strings like "Иван Иванов (60)" or "Иван Иванов"
    not_done: names of users in the users table who haven't planked today
    """
    pool = _get_pool()
    today = get_today_date_str()

    def _callee(session: ydb.Session):
        tx = session.transaction(ydb.SerializableReadWrite())
        tx.begin()

        try:
            done_query = """
                DECLARE $plank_date AS Utf8;

                SELECT u.name AS name, pr.actual_seconds AS actual_seconds
                FROM plank_records AS pr
                JOIN users AS u ON u.user_id = pr.user_id
                WHERE pr.plank_date = $plank_date;
            """
            done_result = tx.execute(done_query, {"$plank_date": today})

            not_done_query = """
                DECLARE $plank_date AS Utf8;

                SELECT u.name AS name
                FROM users AS u
                WHERE u.user_id NOT IN (
                    SELECT user_id FROM plank_records WHERE plank_date = $plank_date
                );
            """
            not_done_result = tx.execute(not_done_query, {"$plank_date": today})

            tx.commit()

            done = []
            for row in done_result[0].rows:
                if row.actual_seconds is not None:
                    done.append(f"{row.name} ({row.actual_seconds})")
                else:
                    done.append(row.name)

            not_done = [row.name for row in not_done_result[0].rows]

            return done, not_done

        except Exception:
            try:
                tx.rollback()
            except Exception:
                pass
            raise

    return pool.retry_operation_sync(_callee)
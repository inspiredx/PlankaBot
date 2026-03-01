"""
YDB database layer for PlankaBot.

Uses the YDB Query API (ydb.QuerySessionPool / ydb.QuerySession), which is the
current recommended approach in the YDB Python SDK.

The driver and session pool are initialized once at module level during cold start
to be reused across warm Cloud Function invocations.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import NamedTuple, Optional

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
# YDB driver / session pool — initialized once at module level (cold start).
# Reused across warm invocations. Tests override _pool directly.
#
# The YDB Python SDK requires the endpoint with the grpcs:// scheme prefix.
# Yandex Cloud may expose the endpoint as either "grpcs://host:port" or just
# "host:port" depending on the attribute used — normalize defensively.
# ---------------------------------------------------------------------------

def _normalize_endpoint(endpoint: str) -> str:
    if endpoint and not endpoint.startswith("grpcs://") and not endpoint.startswith("grpc://"):
        return f"grpcs://{endpoint}"
    return endpoint


# Module-level singletons. Tests replace _pool with a mock before calling db functions.
_driver: Optional[ydb.Driver] = None
_pool: Optional[ydb.QuerySessionPool] = None

if YDB_ENDPOINT and YDB_DATABASE:
    try:
        _endpoint = _normalize_endpoint(YDB_ENDPOINT)
        logger.info("Initializing YDB driver: endpoint=%s database=%s", _endpoint, YDB_DATABASE)
        _driver = ydb.Driver(
            endpoint=_endpoint,
            database=YDB_DATABASE,
            credentials=ydb.iam.MetadataUrlCredentials(),
        )
        _driver.wait(fail_fast=True, timeout=5)
        _pool = ydb.QuerySessionPool(_driver)
        logger.info("YDB session pool ready")
    except Exception as _exc:
        logger.error("Failed to initialize YDB driver at module load: %s", _exc)
        _driver = None
        _pool = None


def _get_pool() -> ydb.QuerySessionPool:
    if _pool is None:
        raise RuntimeError("YDB session pool is not initialized. Check YDB_ENDPOINT and YDB_DATABASE env vars.")
    return _pool


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class PlankMarkResult(NamedTuple):
    """Result of mark_plank."""
    is_new: bool       # True if a new record was inserted
    was_updated: bool  # True if an existing record's actual_seconds was updated


def mark_plank(user_id: int, name: str, actual_seconds: Optional[int]) -> PlankMarkResult:
    """
    Record today's plank for user_id.

    Returns PlankMarkResult:
      - is_new=True, was_updated=False  — first plank of the day inserted
      - is_new=False, was_updated=True  — existing record updated with new actual_seconds
      - is_new=False, was_updated=False — already done, nothing to update

    Uses an explicit SerializableReadWrite transaction:
      1. Read existing user row (to preserve is_bot_admin / created_at)
      2. Upsert user (create or update name + last_activity)
      3. Check for existing plank_records row for today
      4a. If none, insert it
      4b. If exists and actual_seconds provided, update it
    """
    pool = _get_pool()
    today = get_today_date_str()
    now_us = int(datetime.now(timezone.utc).timestamp() * 1_000_000)

    def _callee(session: ydb.QuerySession):
        tx = session.transaction(ydb.QuerySerializableReadWrite())

        try:
            # Step 1: Read existing user row to preserve is_bot_admin and created_at.
            # YDB does not support LEFT JOIN ON true, so we read first and merge in Python.
            with tx.execute(
                """
                DECLARE $user_id AS Int64;

                SELECT is_bot_admin, created_at
                FROM users
                WHERE user_id = $user_id;
                """,
                {"$user_id": user_id},
                commit_tx=False,
            ) as result_sets:
                rows = list(result_sets)[0].rows

            if rows:
                is_bot_admin = rows[0].is_bot_admin
                created_at = rows[0].created_at
            else:
                is_bot_admin = False
                created_at = now_us

            # Step 2: Upsert user with preserved values
            with tx.execute(
                """
                DECLARE $user_id AS Int64;
                DECLARE $name AS Utf8;
                DECLARE $is_bot_admin AS Bool;
                DECLARE $last_activity AS Timestamp;
                DECLARE $created_at AS Timestamp;

                UPSERT INTO users (user_id, name, is_bot_admin, last_activity, created_at)
                VALUES ($user_id, $name, $is_bot_admin, $last_activity, $created_at);
                """,
                {
                    "$user_id": user_id,
                    "$name": name,
                    "$is_bot_admin": is_bot_admin,
                    "$last_activity": (now_us, ydb.PrimitiveType.Timestamp),
                    "$created_at": (created_at, ydb.PrimitiveType.Timestamp),
                },
                commit_tx=False,
            ) as _:
                pass

            # Step 3: Check if plank_records row exists for today
            with tx.execute(
                """
                DECLARE $user_id AS Int64;
                DECLARE $plank_date AS Utf8;

                SELECT COUNT(*) AS cnt
                FROM plank_records
                WHERE user_id = $user_id AND plank_date = $plank_date;
                """,
                {
                    "$user_id": user_id,
                    "$plank_date": today,
                },
                commit_tx=False,
            ) as result_sets:
                rows = list(result_sets)[0].rows
                count = rows[0].cnt if rows else 0

            if count > 0:
                if actual_seconds is not None:
                    # Step 4b: Update existing record with new actual_seconds
                    with tx.execute(
                        """
                        DECLARE $user_id AS Int64;
                        DECLARE $plank_date AS Utf8;
                        DECLARE $actual_seconds AS Int32?;

                        UPDATE plank_records
                        SET actual_seconds = $actual_seconds
                        WHERE user_id = $user_id AND plank_date = $plank_date;
                        """,
                        {
                            "$user_id": user_id,
                            "$plank_date": today,
                            "$actual_seconds": (actual_seconds, ydb.OptionalType(ydb.PrimitiveType.Int32)),
                        },
                        commit_tx=True,
                    ) as _:
                        pass
                    return PlankMarkResult(is_new=False, was_updated=True)
                else:
                    tx.commit()
                    return PlankMarkResult(is_new=False, was_updated=False)

            # Step 4a: Insert plank record and commit
            with tx.execute(
                """
                DECLARE $user_id AS Int64;
                DECLARE $plank_date AS Utf8;
                DECLARE $actual_seconds AS Int32?;
                DECLARE $now AS Timestamp;

                INSERT INTO plank_records (user_id, plank_date, actual_seconds, created_at)
                VALUES ($user_id, $plank_date, $actual_seconds, $now);
                """,
                {
                    "$user_id": user_id,
                    "$plank_date": today,
                    "$actual_seconds": (actual_seconds, ydb.OptionalType(ydb.PrimitiveType.Int32)),
                    "$now": (now_us, ydb.PrimitiveType.Timestamp),
                },
                commit_tx=True,
            ) as _:
                pass

            return PlankMarkResult(is_new=True, was_updated=False)

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

    Uses execute_with_retries for these simple read-only queries.
    """
    pool = _get_pool()
    today = get_today_date_str()

    done_result_sets = pool.execute_with_retries(
        """
        DECLARE $plank_date AS Utf8;

        SELECT u.name AS name, pr.actual_seconds AS actual_seconds
        FROM plank_records AS pr
        JOIN users AS u ON u.user_id = pr.user_id
        WHERE pr.plank_date = $plank_date;
        """,
        {"$plank_date": today},
    )

    not_done_result_sets = pool.execute_with_retries(
        """
        DECLARE $plank_date AS Utf8;

        SELECT u.name AS name
        FROM users AS u
        WHERE u.user_id NOT IN (
            SELECT user_id FROM plank_records WHERE plank_date = $plank_date
        );
        """,
        {"$plank_date": today},
    )

    done = []
    for row in done_result_sets[0].rows:
        if row.actual_seconds is not None:
            done.append(f"{row.name} ({row.actual_seconds})")
        else:
            done.append(row.name)

    not_done = [row.name for row in not_done_result_sets[0].rows]

    return done, not_done
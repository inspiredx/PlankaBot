import json
import logging

import config
from config import VK_CONFIRMATION_TOKEN
from bot import process_message
import db

logger = logging.getLogger(__name__)

# Default peer_id for story export (main group chat)
_DEFAULT_STORY_PEER_ID = 2000000001


def handle_export_story(event):
    """
    Handle GET /current-story.txt — export the active story as plain text.

    Query params:
      peer_id (optional, int) — VK conversation peer_id; defaults to 2000000001.

    Returns 200 with plain text story turns in chronological order,
    or a "no active story" message if none exists.
    """
    params = event.get("queryStringParameters") or {}
    peer_id_str = params.get("peer_id")

    if peer_id_str is not None:
        try:
            peer_id = int(peer_id_str)
        except ValueError:
            return {
                "statusCode": 400,
                "body": "peer_id must be an integer",
                "headers": {"Content-Type": "text/plain; charset=utf-8"},
            }
    else:
        peer_id = _DEFAULT_STORY_PEER_ID

    try:
        turns = db.story_get_turns(peer_id)
    except Exception as e:
        logger.error("Failed to load story turns for export: %s", e)
        return {
            "statusCode": 500,
            "body": "Не удалось загрузить историю. Попробуй позже.",
            "headers": {"Content-Type": "text/plain; charset=utf-8"},
        }

    if not turns:
        return {
            "statusCode": 200,
            "body": "Активной истории нет.",
            "headers": {"Content-Type": "text/plain; charset=utf-8"},
        }

    lines = []
    for turn in turns:
        role_label = "Участник" if turn["role"] == "user" else "Рассказчик"
        lines.append(f"[{role_label}]\n{turn['content']}")

    body = "\n\n".join(lines)
    return {
        "statusCode": 200,
        "body": body,
        "headers": {
            "Content-Type": "text/plain; charset=utf-8",
            "Content-Disposition": 'inline; filename="current-story.txt"',
        },
    }


def handler(event, context):
    """
    Yandex Cloud Functions entry point.

    Routes:
      GET  /current-story.txt — export active story as plain text (no auth)
      POST /                  — VK Callback API webhook (requires VK secret key)

    Expected event shape (HTTP integration):
      {
        "httpMethod": "GET"|"POST",
        "path": "/...",
        "queryStringParameters": {...},
        "body": "<JSON string>",
        "headers": {...},
        ...
      }
    """
    http_method = event.get("httpMethod", "POST").upper()
    path = event.get("path", "/")

    # Route GET /current-story.txt — no secret key required (read-only export)
    if http_method == "GET" and path == "/current-story.txt":
        return handle_export_story(event)

    # All other requests: VK Callback API (POST)
    try:
        body_raw = event.get("body", "{}")
        if isinstance(body_raw, str):
            data = json.loads(body_raw)
        else:
            data = body_raw
    except (json.JSONDecodeError, TypeError) as e:
        logger.error("Failed to parse request body: %s", e)
        return {"statusCode": 400, "body": "bad request"}

    # Validate the VK secret key (required)
    if data.get("secret") != config.VK_SECRET_KEY:
        logger.warning("Rejected request: invalid or missing secret field")
        return {"statusCode": 403, "body": "Forbidden"}

    event_type = data.get("type")
    if event_type == "confirmation":
        return {"statusCode": 200, "body": VK_CONFIRMATION_TOKEN}

    if event_type == "message_new":
        msg = data.get("object", {}).get("message", {})
        try:
            process_message(msg)
        except Exception as e:
            logger.error("Error processing message: %s", e)
            # Still return ok so VK does not retry
            return {"statusCode": 200, "body": "ok"}

    return {"statusCode": 200, "body": "ok"}

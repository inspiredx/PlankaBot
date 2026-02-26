import json
import logging

from config import VK_CONFIRMATION_TOKEN
from bot import process_message

logging.getLogger().setLevel(logging.DEBUG)
logging.getLogger(__name__).setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)

def handler(event, context):
    """
    Yandex Cloud Functions entry point.

    VK sends a POST request to the API Gateway, which forwards it here.
    Expected event shape (HTTP integration):
      {
        "body": "<JSON string>",
        "headers": {...},
        ...
      }
    """

    try:
        body_raw = event.get("body", "{}")
        if isinstance(body_raw, str):
            data = json.loads(body_raw)
        else:
            data = body_raw
    except (json.JSONDecodeError, TypeError) as e:
        logger.error("Failed to parse request body: %s", e)
        return {"statusCode": 400, "body": "bad request"}

    event_type = data.get("type")
    logger.warning("Received VK event type: %s", event_type)

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
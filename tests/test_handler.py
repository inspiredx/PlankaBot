import json
import sys
import os
import pytest
from unittest.mock import patch, MagicMock

# Make src/ importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


@pytest.fixture(autouse=True)
def mock_vk_session():
    """Prevent real VK API initialisation during import of bot.py."""
    with patch("vk_api.VkApi") as mock_cls:
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        mock_instance.get_api.return_value = MagicMock()
        yield mock_cls


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("VK_GROUP_TOKEN", "test_group_token")
    monkeypatch.setenv("VK_CONFIRMATION_TOKEN", "test_confirmation_token")


def make_event(body: dict) -> dict:
    return {"body": json.dumps(body)}


def test_confirmation_event_returns_token():
    # Import here so env vars are set first
    import importlib
    import config
    importlib.reload(config)

    import handler
    importlib.reload(handler)

    event = make_event({"type": "confirmation"})
    result = handler.handler(event, {})

    assert result["statusCode"] == 200
    assert result["body"] == "test_confirmation_token"


def test_unknown_event_returns_ok():
    import importlib
    import handler
    importlib.reload(handler)

    event = make_event({"type": "wall_post_new"})
    result = handler.handler(event, {})

    assert result["statusCode"] == 200
    assert result["body"] == "ok"


def test_invalid_json_returns_400():
    import importlib
    import handler
    importlib.reload(handler)

    event = {"body": "not json {{"}
    result = handler.handler(event, {})

    assert result["statusCode"] == 400


def test_message_new_dispatches_to_process_message():
    import importlib
    import handler
    importlib.reload(handler)

    msg_payload = {
        "type": "message_new",
        "object": {
            "message": {
                "peer_id": 2000000001,
                "from_id": 123456,
                "text": "гайд",
            }
        }
    }

    with patch("handler.process_message") as mock_process:
        result = handler.handler(make_event(msg_payload), {})

    mock_process.assert_called_once()
    assert result["statusCode"] == 200
    assert result["body"] == "ok"


def test_message_new_exception_still_returns_ok():
    import importlib
    import handler
    importlib.reload(handler)

    msg_payload = {
        "type": "message_new",
        "object": {"message": {"peer_id": 2000000001, "from_id": 1, "text": "test"}},
    }

    with patch("handler.process_message", side_effect=RuntimeError("boom")):
        result = handler.handler(make_event(msg_payload), {})

    assert result["statusCode"] == 200
    assert result["body"] == "ok"
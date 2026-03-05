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


TEST_SECRET = "test_secret_key"


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("VK_GROUP_TOKEN", "test_group_token")
    monkeypatch.setenv("VK_CONFIRMATION_TOKEN", "test_confirmation_token")
    monkeypatch.setenv("VK_SECRET_KEY", TEST_SECRET)


def make_event(body: dict) -> dict:
    return {"body": json.dumps(body)}


def test_confirmation_event_returns_token():
    # Import here so env vars are set first
    import importlib
    import config
    importlib.reload(config)

    import handler
    importlib.reload(handler)

    event = make_event({"type": "confirmation", "secret": TEST_SECRET})
    result = handler.handler(event, {})

    assert result["statusCode"] == 200
    assert result["body"] == "test_confirmation_token"


def test_unknown_event_returns_ok():
    import importlib
    import handler
    importlib.reload(handler)

    event = make_event({"type": "wall_post_new", "secret": TEST_SECRET})
    result = handler.handler(event, {})

    assert result["statusCode"] == 200
    assert result["body"] == "ok"


def test_invalid_json_returns_400():
    import importlib
    import handler
    importlib.reload(handler)

    # Secret check happens after JSON parsing, so malformed JSON still returns 400
    event = {"body": "not json {{"}
    result = handler.handler(event, {})

    assert result["statusCode"] == 400


def test_message_new_dispatches_to_process_message():
    import importlib
    import handler
    importlib.reload(handler)

    msg_payload = {
        "type": "message_new",
        "secret": TEST_SECRET,
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
        "secret": TEST_SECRET,
        "object": {"message": {"peer_id": 2000000001, "from_id": 1, "text": "test"}},
    }

    with patch("handler.process_message", side_effect=RuntimeError("boom")):
        result = handler.handler(make_event(msg_payload), {})

    assert result["statusCode"] == 200
    assert result["body"] == "ok"


# ---------------------------------------------------------------------------
# Story export (GET /current-story.txt) tests
# ---------------------------------------------------------------------------

class TestStoryExport:
    """Tests for GET /current-story.txt endpoint."""

    def _reload_handler(self):
        import importlib
        import handler as h
        importlib.reload(h)
        return h

    def test_get_story_no_peer_id_uses_default(self):
        """GET without peer_id param defaults to 2000000001 and returns story text."""
        h = self._reload_handler()

        turns = [
            {"role": "user", "content": "начать историю про котов"},
            {"role": "assistant", "content": "Однажды в большом городе жил кот..."},
            {"role": "user", "content": "и у него была шляпа"},
        ]
        event = {"httpMethod": "GET", "path": "/current-story.txt", "queryStringParameters": None}

        with patch("handler.db.story_get_turns", return_value=turns) as mock_turns:
            result = h.handler(event, {})

        mock_turns.assert_called_once_with(2000000001)
        assert result["statusCode"] == 200
        assert "Участник" in result["body"]
        assert "Рассказчик" in result["body"]
        assert "начать историю про котов" in result["body"]
        assert "Однажды в большом городе жил кот..." in result["body"]
        assert result["headers"]["Content-Type"] == "text/plain; charset=utf-8"

    def test_get_story_with_explicit_peer_id(self):
        """GET with explicit peer_id uses that value."""
        h = self._reload_handler()

        turns = [
            {"role": "user", "content": "тема"},
            {"role": "assistant", "content": "Жил-был..."},
        ]
        event = {
            "httpMethod": "GET",
            "path": "/current-story.txt",
            "queryStringParameters": {"peer_id": "2000000042"},
        }

        with patch("handler.db.story_get_turns", return_value=turns) as mock_turns:
            result = h.handler(event, {})

        mock_turns.assert_called_once_with(2000000042)
        assert result["statusCode"] == 200

    def test_get_story_no_active_story_returns_message(self):
        """GET when no story is active returns 200 with a 'no story' message."""
        h = self._reload_handler()

        event = {"httpMethod": "GET", "path": "/current-story.txt", "queryStringParameters": None}

        with patch("handler.db.story_get_turns", return_value=[]):
            result = h.handler(event, {})

        assert result["statusCode"] == 200
        assert "Активной истории нет" in result["body"]
        assert result["headers"]["Content-Type"] == "text/plain; charset=utf-8"

    def test_get_story_invalid_peer_id_returns_400(self):
        """GET with non-integer peer_id returns 400."""
        h = self._reload_handler()

        event = {
            "httpMethod": "GET",
            "path": "/current-story.txt",
            "queryStringParameters": {"peer_id": "not-a-number"},
        }

        result = h.handler(event, {})

        assert result["statusCode"] == 400
        assert "peer_id must be an integer" in result["body"]

    def test_get_story_db_error_returns_500(self):
        """GET when DB raises an exception returns 500."""
        h = self._reload_handler()

        event = {"httpMethod": "GET", "path": "/current-story.txt", "queryStringParameters": None}

        with patch("handler.db.story_get_turns", side_effect=RuntimeError("db down")):
            result = h.handler(event, {})

        assert result["statusCode"] == 500

    def test_get_story_does_not_require_secret(self):
        """GET /current-story.txt bypasses VK secret key validation."""
        h = self._reload_handler()

        event = {
            "httpMethod": "GET",
            "path": "/current-story.txt",
            "queryStringParameters": None,
            # No 'secret' field — would normally be rejected for POST
        }

        with patch("handler.db.story_get_turns", return_value=[]):
            result = h.handler(event, {})

        # Should return 200 (no story), not 403
        assert result["statusCode"] == 200

    def test_get_story_turn_labels(self):
        """Story turns are labelled correctly: user→Участник, assistant→Рассказчик."""
        h = self._reload_handler()

        turns = [
            {"role": "user", "content": "user line"},
            {"role": "assistant", "content": "assistant line"},
        ]
        event = {"httpMethod": "GET", "path": "/current-story.txt", "queryStringParameters": None}

        with patch("handler.db.story_get_turns", return_value=turns):
            result = h.handler(event, {})

        body = result["body"]
        assert "[Участник]\nuser line" in body
        assert "[Рассказчик]\nassistant line" in body

    def test_post_route_still_works_after_get_added(self):
        """Existing POST / VK callback route is unaffected by the new GET route."""
        h = self._reload_handler()

        event = make_event({"type": "wall_post_new", "secret": TEST_SECRET})
        result = h.handler(event, {})

        assert result["statusCode"] == 200
        assert result["body"] == "ok"


# ---------------------------------------------------------------------------
# VK secret key validation tests
# ---------------------------------------------------------------------------

class TestSecretKeyValidation:
    """Tests for VK Callback API secret field validation."""

    def _reload_handler_with_secret(self, monkeypatch, secret_value):
        """Helper: set VK_SECRET_KEY env var and reload handler + config."""
        import importlib
        import config as cfg
        import handler as h

        monkeypatch.setenv("VK_SECRET_KEY", secret_value)
        importlib.reload(cfg)
        importlib.reload(h)
        return h

    def test_correct_secret_passes(self, monkeypatch):
        h = self._reload_handler_with_secret(monkeypatch, "mysecret")
        event = make_event({"type": "message_new", "secret": "mysecret",
                            "object": {"message": {"peer_id": 2000000001, "from_id": 1, "text": "гайд"}}})
        with patch("handler.process_message"):
            result = h.handler(event, {})
        assert result["statusCode"] == 200

    def test_wrong_secret_returns_403(self, monkeypatch):
        h = self._reload_handler_with_secret(monkeypatch, "mysecret")
        event = make_event({"type": "message_new", "secret": "wrongsecret",
                            "object": {"message": {"peer_id": 2000000001, "from_id": 1, "text": "гайд"}}})
        result = h.handler(event, {})
        assert result["statusCode"] == 403
        assert result["body"] == "Forbidden"

    def test_missing_secret_field_returns_403(self, monkeypatch):
        h = self._reload_handler_with_secret(monkeypatch, "mysecret")
        event = make_event({"type": "message_new",
                            "object": {"message": {"peer_id": 2000000001, "from_id": 1, "text": "гайд"}}})
        result = h.handler(event, {})
        assert result["statusCode"] == 403
        assert result["body"] == "Forbidden"

    def test_no_secret_field_when_key_configured_returns_403(self, monkeypatch):
        """A request with no secret field at all is rejected even if secret key is configured."""
        h = self._reload_handler_with_secret(monkeypatch, "mysecret")
        event = make_event({"type": "wall_post_new"})
        result = h.handler(event, {})
        assert result["statusCode"] == 403

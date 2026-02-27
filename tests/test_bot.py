import sys
import os
import pytest
from unittest.mock import patch, MagicMock, call

# Make src/ importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


@pytest.fixture(autouse=True)
def mock_vk_session():
    with patch("vk_api.VkApi") as mock_cls:
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        mock_instance.get_api.return_value = MagicMock()
        yield mock_cls


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("VK_GROUP_TOKEN", "test_group_token")
    monkeypatch.setenv("VK_CONFIRMATION_TOKEN", "test_confirmation_token")
    monkeypatch.setenv("YANDEX_FOLDER_ID", "test_folder_id")
    monkeypatch.setenv("YANDEX_LLM_API_KEY", "test_llm_api_key")


@pytest.fixture()
def bot_module():
    import importlib
    import config
    importlib.reload(config)
    import bot
    importlib.reload(bot)
    return bot


def make_msg(text: str, peer_id: int = 2000000001, from_id: int = 111):
    return {"text": text, "peer_id": peer_id, "from_id": from_id}


class TestProcessMessageRouting:
    def test_ignores_private_messages(self, bot_module):
        """Messages with peer_id < 2_000_000_000 are ignored (private chats)."""
        with patch.object(bot_module, "handle_guide") as mock_guide:
            bot_module.process_message(make_msg("гайд", peer_id=111))
        mock_guide.assert_not_called()

    def test_routes_guide_command(self, bot_module):
        with patch.object(bot_module, "handle_guide") as mock_fn:
            bot_module.process_message(make_msg("гайд"))
        mock_fn.assert_called_once()

    def test_routes_stats_command(self, bot_module):
        with patch.object(bot_module, "handle_stats") as mock_fn:
            bot_module.process_message(make_msg("стата"))
        mock_fn.assert_called_once()

    def test_routes_geese_command(self, bot_module):
        with patch.object(bot_module, "handle_geese") as mock_fn:
            bot_module.process_message(make_msg("ебать гусей"))
        mock_fn.assert_called_once()

    def test_routes_geese_command_with_context(self, bot_module):
        with patch.object(bot_module, "handle_geese") as mock_fn:
            bot_module.process_message(make_msg("ебать гусей причмокивая"))
        mock_fn.assert_called_once()

    def test_routes_planka_command(self, bot_module):
        with patch.object(bot_module, "handle_planka") as mock_fn:
            bot_module.process_message(make_msg("планка"))
        mock_fn.assert_called_once()

    def test_routes_planka_with_value(self, bot_module):
        with patch.object(bot_module, "handle_planka") as mock_fn:
            bot_module.process_message(make_msg("Планка 60"))
        mock_fn.assert_called_once()

    def test_ignores_planka_with_extra_args(self, bot_module):
        """'планка 60 sec extra' has 4 parts — should not be handled."""
        with patch.object(bot_module, "handle_planka") as mock_fn:
            bot_module.process_message(make_msg("планка 60 sec extra"))
        mock_fn.assert_not_called()

    def test_unknown_command_does_nothing(self, bot_module):
        with patch.object(bot_module, "send_message") as mock_send:
            bot_module.process_message(make_msg("hello world"))
        mock_send.assert_not_called()


class TestHandleGuide:
    def test_sends_guide_text(self, bot_module):
        msg = make_msg("гайд")
        with patch.object(bot_module, "send_message") as mock_send:
            bot_module.handle_guide(msg)
        mock_send.assert_called_once()
        args = mock_send.call_args[0]
        assert args[0] == msg["peer_id"]
        assert "планка" in args[1]
        assert "стата" in args[1]


class TestHandleGeese:
    def test_placeholder_messages_list_has_10_entries(self, bot_module):
        assert len(bot_module.GEESE_PLACEHOLDER_MESSAGES) == 10

    def test_all_placeholder_messages_are_non_empty_strings(self, bot_module):
        for msg in bot_module.GEESE_PLACEHOLDER_MESSAGES:
            assert isinstance(msg, str) and len(msg) > 0

    def test_sends_placeholder_first_then_story(self, bot_module):
        """Two send_message calls: placeholder first, story second."""
        msg = make_msg("ебать гусей")
        story_text = "Мудрая история про гусей. Сделай планку."

        with patch.object(bot_module, "send_message") as mock_send, \
             patch.object(bot_module, "_call_llm", return_value=story_text):
            bot_module.handle_geese(msg, "ебать гусей")

        assert mock_send.call_count == 2
        first_call_text = mock_send.call_args_list[0][0][1]
        second_call_text = mock_send.call_args_list[1][0][1]
        assert first_call_text in bot_module.GEESE_PLACEHOLDER_MESSAGES
        assert second_call_text == story_text + "\n\nВы ебете гусей."

    def test_extra_context_parsed_correctly(self, bot_module):
        """Extra context after 'ебать гусей' is passed to the LLM."""
        msg = make_msg("ебать гусей причмокивая")

        with patch.object(bot_module, "send_message"), \
             patch.object(bot_module, "_call_llm", return_value="story") as mock_llm:
            bot_module.handle_geese(msg, "ебать гусей причмокивая")

        mock_llm.assert_called_once_with("причмокивая")

    def test_no_extra_context_passes_empty_string(self, bot_module):
        msg = make_msg("ебать гусей")

        with patch.object(bot_module, "send_message"), \
             patch.object(bot_module, "_call_llm", return_value="story") as mock_llm:
            bot_module.handle_geese(msg, "ебать гусей")

        mock_llm.assert_called_once_with("")

    def test_llm_failure_sends_error_message(self, bot_module):
        """If LLM throws, user gets a friendly error message instead of crashing."""
        msg = make_msg("ебать гусей")

        with patch.object(bot_module, "send_message") as mock_send, \
             patch.object(bot_module, "_call_llm", side_effect=RuntimeError("api error")):
            bot_module.handle_geese(msg, "ебать гусей")

        assert mock_send.call_count == 2
        error_text = mock_send.call_args_list[1][0][1]
        assert "Гуси молчат" in error_text

    def test_peer_id_correct_in_both_messages(self, bot_module):
        msg = make_msg("ебать гусей", peer_id=2000000042)

        with patch.object(bot_module, "send_message") as mock_send, \
             patch.object(bot_module, "_call_llm", return_value="story"):
            bot_module.handle_geese(msg, "ебать гусей")

        for c in mock_send.call_args_list:
            assert c[0][0] == 2000000042

    def test_random_placeholder_is_used(self, bot_module):
        """Verify random.choice is called with GEESE_PLACEHOLDER_MESSAGES."""
        msg = make_msg("ебать гусей")
        with patch("bot.random.choice", return_value=bot_module.GEESE_PLACEHOLDER_MESSAGES[0]) as mock_choice, \
             patch.object(bot_module, "send_message"), \
             patch.object(bot_module, "_call_llm", return_value="story"):
            bot_module.handle_geese(msg, "ебать гусей")
        mock_choice.assert_called_once_with(bot_module.GEESE_PLACEHOLDER_MESSAGES)

    def test_extra_context_case_insensitive_trigger(self, bot_module):
        """Trigger is matched case-insensitively; context still extracted correctly."""
        msg = make_msg("Ебать Гусей ГРОМКО")

        with patch.object(bot_module, "send_message"), \
             patch.object(bot_module, "_call_llm", return_value="story") as mock_llm:
            bot_module.handle_geese(msg, "Ебать Гусей ГРОМКО")

        mock_llm.assert_called_once_with("ГРОМКО")


class TestHandleStats:
    def test_stats_returns_unavailable(self, bot_module):
        msg = make_msg("стата")
        with patch.object(bot_module, "send_message") as mock_send:
            bot_module.handle_stats(msg)
        mock_send.assert_called_once()
        assert "недоступна" in mock_send.call_args[0][1]


class TestHandlePlanka:
    def test_planka_no_value(self, bot_module):
        msg = make_msg("планка")
        with patch.object(bot_module, "send_message") as mock_send:
            bot_module.handle_planka(msg, "планка")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][1]
        assert "планка сделана" in text
        assert "(" not in text

    def test_planka_with_value(self, bot_module):
        msg = make_msg("планка 60")
        with patch.object(bot_module, "send_message") as mock_send:
            bot_module.handle_planka(msg, "планка 60")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][1]
        assert "планка сделана" in text
        assert "(60)" in text
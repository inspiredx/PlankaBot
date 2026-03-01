import sys
import os
import pytest
from unittest.mock import patch, MagicMock

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
    monkeypatch.setenv("VK_SECRET_KEY", "test_secret_key")
    monkeypatch.setenv("YANDEX_FOLDER_ID", "test_folder_id")
    monkeypatch.setenv("YANDEX_LLM_API_KEY", "test_llm_api_key")
    monkeypatch.delenv("YDB_ENDPOINT", raising=False)
    monkeypatch.delenv("YDB_DATABASE", raising=False)
    monkeypatch.setenv("PLANK_TIMEZONE", "Europe/Moscow")


@pytest.fixture()
def bot_module():
    import importlib
    import config
    importlib.reload(config)
    import db
    importlib.reload(db)
    import bot
    importlib.reload(bot)
    return bot


@pytest.fixture()
def db_module(bot_module):
    """Return the db module as imported by bot (same reload cycle)."""
    import db
    return db


def make_msg(text: str, peer_id: int = 2000000001, from_id: int = 111):
    return {"text": text, "peer_id": peer_id, "from_id": from_id}


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# handle_guide
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# handle_geese
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# handle_stats
# ---------------------------------------------------------------------------

class TestHandleStats:
    def test_stats_nobody_done(self, bot_module, db_module):
        """When nobody planked today, response says 'никто'."""
        msg = make_msg("стата")
        with patch.object(db_module, "get_stats_for_today", return_value=([], [])), \
             patch.object(db_module, "get_today_date_str", return_value="2026-03-01"), \
             patch.object(bot_module, "send_message") as mock_send:
            bot_module.handle_stats(msg)
        mock_send.assert_called_once()
        text = mock_send.call_args[0][1]
        assert "2026-03-01" in text
        assert "никто" in text

    def test_stats_done_and_not_done(self, bot_module, db_module):
        """Shows both done and not-done lists."""
        msg = make_msg("стата")
        done = ["Иван Иванов (60)", "Мария Смирнова"]
        not_done = ["Пётр Петров"]
        with patch.object(db_module, "get_stats_for_today", return_value=(done, not_done)), \
             patch.object(db_module, "get_today_date_str", return_value="2026-03-01"), \
             patch.object(bot_module, "send_message") as mock_send:
            bot_module.handle_stats(msg)
        text = mock_send.call_args[0][1]
        assert "Иван Иванов (60)" in text
        assert "Мария Смирнова" in text
        assert "Пётр Петров" in text

    def test_stats_all_done(self, bot_module, db_module):
        """When not_done is empty, message says everyone is done."""
        msg = make_msg("стата")
        with patch.object(db_module, "get_stats_for_today", return_value=(["Иван Иванов"], [])), \
             patch.object(db_module, "get_today_date_str", return_value="2026-03-01"), \
             patch.object(bot_module, "send_message") as mock_send:
            bot_module.handle_stats(msg)
        text = mock_send.call_args[0][1]
        assert "Все отметились" in text


# ---------------------------------------------------------------------------
# handle_planka
# ---------------------------------------------------------------------------

class TestHandlePlanka:
    def _new_result(self, db_module):
        return db_module.PlankMarkResult(is_new=True, was_updated=False)

    def _dup_result(self, db_module):
        return db_module.PlankMarkResult(is_new=False, was_updated=False)

    def _updated_result(self, db_module):
        return db_module.PlankMarkResult(is_new=False, was_updated=True)

    def test_planka_no_value_first_today(self, bot_module, db_module):
        """First plank of the day without value → success message."""
        msg = make_msg("планка")
        with patch.object(db_module, "mark_plank", return_value=self._new_result(db_module)), \
             patch.object(db_module, "get_today_date_str", return_value="2026-03-01"), \
             patch.object(bot_module, "get_user_name", return_value="Иван Иванов"), \
             patch.object(bot_module, "send_message") as mock_send:
            bot_module.handle_planka(msg, "планка")
        text = mock_send.call_args[0][1]
        assert "планка сделана" in text
        assert "(" not in text
        assert "2026-03-01" in text

    def test_planka_with_value_first_today(self, bot_module, db_module):
        """First plank of the day with value → success message with seconds."""
        msg = make_msg("планка 60")
        with patch.object(db_module, "mark_plank", return_value=self._new_result(db_module)) as mock_mark, \
             patch.object(db_module, "get_today_date_str", return_value="2026-03-01"), \
             patch.object(bot_module, "get_user_name", return_value="Иван Иванов"), \
             patch.object(bot_module, "send_message") as mock_send:
            bot_module.handle_planka(msg, "планка 60")
        text = mock_send.call_args[0][1]
        assert "планка сделана" in text
        assert "(60)" in text
        mock_mark.assert_called_once_with(111, "Иван Иванов", 60)

    def test_planka_duplicate_no_value(self, bot_module, db_module):
        """Already planked today, no new value → 'уже сделана' (no seconds shown)."""
        msg = make_msg("планка")
        with patch.object(db_module, "mark_plank", return_value=self._dup_result(db_module)), \
             patch.object(db_module, "get_today_date_str", return_value="2026-03-01"), \
             patch.object(bot_module, "get_user_name", return_value="Иван Иванов"), \
             patch.object(bot_module, "send_message") as mock_send:
            bot_module.handle_planka(msg, "планка")
        text = mock_send.call_args[0][1]
        assert "уже сделана" in text
        assert "(" not in text

    def test_planka_duplicate_no_value_does_not_show_stale_seconds(self, bot_module, db_module):
        """Sending 'планка' when already done shows no seconds (doesn't echo stale DB value)."""
        msg = make_msg("планка")
        with patch.object(db_module, "mark_plank", return_value=self._dup_result(db_module)), \
             patch.object(db_module, "get_today_date_str", return_value="2026-03-01"), \
             patch.object(bot_module, "get_user_name", return_value="Иван Иванов"), \
             patch.object(bot_module, "send_message") as mock_send:
            bot_module.handle_planka(msg, "планка")
        text = mock_send.call_args[0][1]
        assert "(" not in text

    def test_planka_update_with_seconds(self, bot_module, db_module):
        """Already done, new seconds provided → record updated, message says 'обновлена'."""
        msg = make_msg("планка 120")
        with patch.object(db_module, "mark_plank", return_value=self._updated_result(db_module)), \
             patch.object(db_module, "get_today_date_str", return_value="2026-03-01"), \
             patch.object(bot_module, "get_user_name", return_value="Иван Иванов"), \
             patch.object(bot_module, "send_message") as mock_send:
            bot_module.handle_planka(msg, "планка 120")
        text = mock_send.call_args[0][1]
        assert "обновлена" in text
        assert "(120)" in text

    def test_planka_update_message_does_not_say_already_done(self, bot_module, db_module):
        """Updated plank message must NOT say 'уже сделана'."""
        msg = make_msg("планка 60")
        with patch.object(db_module, "mark_plank", return_value=self._updated_result(db_module)), \
             patch.object(db_module, "get_today_date_str", return_value="2026-03-01"), \
             patch.object(bot_module, "get_user_name", return_value="Иван Иванов"), \
             patch.object(bot_module, "send_message") as mock_send:
            bot_module.handle_planka(msg, "планка 60")
        text = mock_send.call_args[0][1]
        assert "уже сделана" not in text

    def test_planka_non_numeric_value_treated_as_no_value(self, bot_module, db_module):
        """Non-numeric second word: actual_seconds passed as None."""
        msg = make_msg("планка abc")
        with patch.object(db_module, "mark_plank", return_value=self._new_result(db_module)) as mock_mark, \
             patch.object(db_module, "get_today_date_str", return_value="2026-03-01"), \
             patch.object(bot_module, "get_user_name", return_value="Иван Иванов"), \
             patch.object(bot_module, "send_message"):
            bot_module.handle_planka(msg, "планка abc")
        mock_mark.assert_called_once_with(111, "Иван Иванов", None)

    def test_planka_passes_user_id_and_name(self, bot_module, db_module):
        """user_id and name are correctly passed to db.mark_plank."""
        msg = make_msg("планка", from_id=999)
        with patch.object(db_module, "mark_plank", return_value=self._new_result(db_module)) as mock_mark, \
             patch.object(db_module, "get_today_date_str", return_value="2026-03-01"), \
             patch.object(bot_module, "get_user_name", return_value="Тест Пользователь"), \
             patch.object(bot_module, "send_message"):
            bot_module.handle_planka(msg, "планка")
        mock_mark.assert_called_once_with(999, "Тест Пользователь", None)


# ---------------------------------------------------------------------------
# process_message — message tracking
# ---------------------------------------------------------------------------

class TestProcessMessageTracking:
    def test_saves_message_on_every_group_chat_message(self, bot_module, db_module):
        """Every message in a group chat is saved to chat_messages."""
        msg = make_msg("привет", peer_id=2000000001, from_id=111)
        msg["id"] = 42
        with patch.object(bot_module, "get_user_name", return_value="Иван Иванов"), \
             patch.object(db_module, "save_message") as mock_save, \
             patch.object(bot_module, "send_message"):
            bot_module.process_message(msg)
        mock_save.assert_called_once_with("42", 111, "Иван Иванов", "привет")

    def test_save_message_failure_does_not_prevent_routing(self, bot_module, db_module):
        """If save_message raises, the command is still handled."""
        msg = make_msg("гайд", peer_id=2000000001, from_id=111)
        msg["id"] = 1
        with patch.object(bot_module, "get_user_name", return_value="Иван Иванов"), \
             patch.object(db_module, "save_message", side_effect=RuntimeError("db down")), \
             patch.object(bot_module, "handle_guide") as mock_guide:
            bot_module.process_message(msg)
        mock_guide.assert_called_once()

    def test_does_not_save_message_for_private_chats(self, bot_module, db_module):
        """Private messages (peer_id < 2_000_000_000) are not saved."""
        msg = make_msg("привет", peer_id=111, from_id=111)
        msg["id"] = 99
        with patch.object(bot_module, "get_user_name", return_value="Иван Иванов"), \
             patch.object(db_module, "save_message") as mock_save:
            bot_module.process_message(msg)
        mock_save.assert_not_called()

    def test_does_not_save_empty_text(self, bot_module, db_module):
        """Messages with empty text are not saved."""
        msg = {"text": "", "peer_id": 2000000001, "from_id": 111, "id": 5}
        with patch.object(bot_module, "get_user_name", return_value="Иван Иванов"), \
             patch.object(db_module, "save_message") as mock_save, \
             patch.object(bot_module, "send_message"):
            bot_module.process_message(msg)
        mock_save.assert_not_called()


# ---------------------------------------------------------------------------
# Routing — кто сегодня
# ---------------------------------------------------------------------------

class TestProcessMessageRoutingWhoIsToday:
    def test_routes_kto_segodnya_command(self, bot_module):
        with patch.object(bot_module, "handle_who_is_today") as mock_fn, \
             patch.object(bot_module, "get_user_name", return_value="Иван"), \
             patch("db.save_message"):
            bot_module.process_message(make_msg("кто сегодня самый красивый"))
        mock_fn.assert_called_once()

    def test_routes_kto_segodnya_with_multiword_context(self, bot_module):
        with patch.object(bot_module, "handle_who_is_today") as mock_fn, \
             patch.object(bot_module, "get_user_name", return_value="Иван"), \
             patch("db.save_message"):
            bot_module.process_message(make_msg("кто сегодня больше всех похож на Цоя"))
        mock_fn.assert_called_once()


# ---------------------------------------------------------------------------
# handle_who_is_today
# ---------------------------------------------------------------------------

class TestHandleWhoIsToday:
    def _make_user_messages(self):
        return [
            ("Иван Иванов", ["Привет", "я сегодня попал под автобус"]),
            ("Мария Смирнова", ["всё хорошо"]),
        ]

    def test_no_question_sends_hint(self, bot_module, db_module):
        """Empty question after 'кто сегодня' → sends usage hint."""
        msg = make_msg("кто сегодня")
        with patch.object(bot_module, "send_message") as mock_send, \
             patch.object(db_module, "get_messages_for_today") as mock_get:
            bot_module.handle_who_is_today(msg, "кто сегодня")
        mock_send.assert_called_once()
        assert "вопрос" in mock_send.call_args[0][1].lower() or "укажи" in mock_send.call_args[0][1].lower()
        mock_get.assert_not_called()

    def test_sends_placeholder_then_verdict(self, bot_module, db_module):
        """Two send_message calls: placeholder first, verdict second."""
        msg = make_msg("кто сегодня самый красивый")
        with patch.object(bot_module, "send_message") as mock_send, \
             patch.object(db_module, "get_messages_for_today", return_value=self._make_user_messages()), \
             patch.object(bot_module, "_call_who_is_today_llm", return_value="Победитель: Иван"):
            bot_module.handle_who_is_today(msg, "кто сегодня самый красивый")
        assert mock_send.call_count == 2
        placeholder = mock_send.call_args_list[0][0][1]
        assert placeholder in bot_module.WHO_IS_TODAY_PLACEHOLDER_MESSAGES
        verdict = mock_send.call_args_list[1][0][1]
        assert verdict == "Победитель: Иван"

    def test_extracts_question_correctly(self, bot_module, db_module):
        """Question after 'кто сегодня' is extracted and passed to LLM."""
        msg = make_msg("кто сегодня самый вонючий")
        with patch.object(bot_module, "send_message"), \
             patch.object(db_module, "get_messages_for_today", return_value=[]), \
             patch.object(bot_module, "_call_who_is_today_llm", return_value="ответ") as mock_llm:
            bot_module.handle_who_is_today(msg, "кто сегодня самый вонючий")
        mock_llm.assert_called_once()
        question_arg = mock_llm.call_args[0][0]
        assert question_arg == "самый вонючий"

    def test_case_insensitive_trigger(self, bot_module, db_module):
        """Trigger matched case-insensitively; question extracted correctly."""
        msg = make_msg("Кто Сегодня САМЫЙ КРАСИВЫЙ")
        with patch.object(bot_module, "send_message"), \
             patch.object(db_module, "get_messages_for_today", return_value=[]), \
             patch.object(bot_module, "_call_who_is_today_llm", return_value="ответ") as mock_llm:
            bot_module.handle_who_is_today(msg, "Кто Сегодня САМЫЙ КРАСИВЫЙ")
        question_arg = mock_llm.call_args[0][0]
        assert question_arg == "САМЫЙ КРАСИВЫЙ"

    def test_db_failure_sends_error_message(self, bot_module, db_module):
        """If get_messages_for_today raises, user gets an error message."""
        msg = make_msg("кто сегодня самый красивый")
        with patch.object(bot_module, "send_message") as mock_send, \
             patch.object(db_module, "get_messages_for_today", side_effect=RuntimeError("db error")):
            bot_module.handle_who_is_today(msg, "кто сегодня самый красивый")
        # placeholder + error
        assert mock_send.call_count == 2
        error_text = mock_send.call_args_list[1][0][1]
        assert "не удалось" in error_text.lower() or "пошло не так" in error_text.lower()

    def test_llm_failure_sends_error_message(self, bot_module, db_module):
        """If LLM raises, user gets an error message."""
        msg = make_msg("кто сегодня самый красивый")
        with patch.object(bot_module, "send_message") as mock_send, \
             patch.object(db_module, "get_messages_for_today", return_value=self._make_user_messages()), \
             patch.object(bot_module, "_call_who_is_today_llm", side_effect=RuntimeError("llm error")):
            bot_module.handle_who_is_today(msg, "кто сегодня самый красивый")
        assert mock_send.call_count == 2
        error_text = mock_send.call_args_list[1][0][1]
        assert "пошло не так" in error_text.lower()

    def test_peer_id_used_for_all_messages(self, bot_module, db_module):
        """All send_message calls use the correct peer_id."""
        msg = make_msg("кто сегодня красивый", peer_id=2000000099)
        with patch.object(bot_module, "send_message") as mock_send, \
             patch.object(db_module, "get_messages_for_today", return_value=[]), \
             patch.object(bot_module, "_call_who_is_today_llm", return_value="ответ"):
            bot_module.handle_who_is_today(msg, "кто сегодня красивый")
        for c in mock_send.call_args_list:
            assert c[0][0] == 2000000099

    def test_who_is_today_placeholder_messages_non_empty(self, bot_module):
        assert len(bot_module.WHO_IS_TODAY_PLACEHOLDER_MESSAGES) > 0
        for m in bot_module.WHO_IS_TODAY_PLACEHOLDER_MESSAGES:
            assert isinstance(m, str) and len(m) > 0


# ---------------------------------------------------------------------------
# _build_who_is_today_input — token economy
# ---------------------------------------------------------------------------

class TestBuildWhoIsTodayInput:
    def test_empty_messages_returns_no_messages_text(self, bot_module):
        result = bot_module._build_who_is_today_input("самый красивый", [])
        assert "самый красивый" in result
        assert "нет" in result.lower()

    def test_includes_question_in_output(self, bot_module):
        user_msgs = [("Иван Иванов", ["Привет"])]
        result = bot_module._build_who_is_today_input("больше всех похож на Цоя", user_msgs)
        assert "больше всех похож на Цоя" in result

    def test_includes_user_name_in_output(self, bot_module):
        user_msgs = [("Иван Иванов", ["Привет"]), ("Мария Смирнова", ["Пока"])]
        result = bot_module._build_who_is_today_input("вопрос", user_msgs)
        assert "Иван Иванов" in result
        assert "Мария Смирнова" in result

    def test_includes_messages_in_output(self, bot_module):
        user_msgs = [("Иван Иванов", ["Попал под автобус"])]
        result = bot_module._build_who_is_today_input("похож на Цоя", user_msgs)
        assert "Попал под автобус" in result

    def test_per_user_budget_limits_total_chars(self, bot_module):
        """Output stays within roughly the character budget."""
        # Create a single user with very many long messages
        long_msgs = ["А" * 10_000] * 50  # 500,000 chars total
        user_msgs = [("Болтун Максимальный", long_msgs)]
        result = bot_module._build_who_is_today_input("вопрос", user_msgs)
        # With 1 user, budget is ~93,000 chars; output should not be astronomically large
        assert len(result) < 110_000

    def test_fair_split_across_users(self, bot_module):
        """Each user gets roughly equal share of the budget."""
        msgs_a = ["А" * 1000] * 200  # 200,000 chars
        msgs_b = ["Б" * 1000] * 200
        user_msgs = [("Пользователь А", msgs_a), ("Пользователь Б", msgs_b)]
        result = bot_module._build_who_is_today_input("вопрос", user_msgs)
        count_a = result.count("А")
        count_b = result.count("Б")
        # Both users should have similar representation (within 10% of each other)
        assert abs(count_a - count_b) < max(count_a, count_b) * 0.1

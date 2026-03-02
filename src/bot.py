import logging
import os
import random
import vk_api
from vk_api.utils import get_random_id

import openai

from config import VK_GROUP_TOKEN, YANDEX_FOLDER_ID, YANDEX_LLM_API_KEY
import db

logger = logging.getLogger(__name__)

DEFAULT_MAX_OUTPUT_TOKENS = 300
DEFAULT_MODEL= 'yandexgpt/rc'
DEFAULT_TEMPERATURE = 0.9

# ---------------------------------------------------------------------------
# Load prompts once at module import time.
# In the deployed function files live at prompts/<name> relative to cwd;
# fall back to the repo path for tests.
# ---------------------------------------------------------------------------
def _load_prompt(filename: str) -> str:
    paths = [
        os.path.join(os.path.dirname(__file__), "prompts", filename),
        os.path.join(os.path.dirname(__file__), "..", "src", "prompts", filename),
    ]
    for p in paths:
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                return f.read().strip()
    return ""

GEESE_STORY_PROMPT = _load_prompt("geese_story_prompt.txt")
WHO_IS_TODAY_PROMPT = _load_prompt("who_is_today_prompt.txt")
EXPLAIN_PROMPT = _load_prompt("explain_prompt.txt")

# ---------------------------------------------------------------------------
# Token economy constants for кто сегодня
# ---------------------------------------------------------------------------
# Model context: 32,768 tokens.
# Reserve ~1,000 for system prompt + instruction overhead, ~500 for output.
# Remaining budget for user messages: ~31,000 tokens.
# Rough estimate: 1 token ≈ 3.5 Russian characters.
_WHO_IS_TODAY_CHAR_BUDGET = 31_000 * 3  # ~93,000 chars total for all users
_WHO_IS_TODAY_MAX_OUTPUT_TOKENS = DEFAULT_MAX_OUTPUT_TOKENS

GEESE_PLACEHOLDER_MESSAGES = [
    "Ну хорошо хорошо, сейчас подумаем, что можно сделать…",
    "Гуси уже в курсе. Собираем мудрость…",
    "Один момент, консультируюсь со стаей…",
    "Ладно, дай собраться с мыслями. Гуси думают.",
    "Принято. Открываю книгу гусиной мудрости…",
    "Хм, интересный запрос. Гуси совещаются…",
    "Сейчас, сейчас. Главный гусь берёт слово…",
    "Ок, запрос принят. Жди гусиного откровения.",
    "Стая собирается. Это займёт секунду…",
    "Молчу, думаю, пишу. Гуси не торопятся.",
]

WHO_IS_TODAY_PLACEHOLDER_MESSAGES = [
    "Изучаю переписку… это займёт секунду.",
    "Листаю чат, ищу достойного кандидата…",
    "Анализирую улики. Кто-то сегодня явно отличился.",
    "Один момент, провожу расследование…",
    "Сейчас разберёмся, кто тут герой дня.",
]

EXPLAIN_PLACEHOLDER_MESSAGES = [
    "Минуту, перевариваю текст…",
    "Уже читаю. Сейчас объясню.",
    "Хм, интересно. Перекладываю на нужный язык…",
    "Осмысляю. Жди.",
    "Секунду — ищу подходящие слова.",
]

DEFAULT_EXPLAIN_STYLES = [
    "по-пацански",
    "как Шекспир",
    "как диктор советского радио",
    "как рэпер из 90-х",
    "как уставший учитель химии",
    "как стартапер на питче",
    "как бабушка на лавочке",
    "как футбольный комментатор",
    "как военный на брифинге",
    "как философ-экзистенциалист",
]


def _get_vk():
    vk_session = vk_api.VkApi(token=VK_GROUP_TOKEN)
    return vk_session.get_api()


def send_message(peer_id, text):
    logger.info("Sending message to peer_id=%s: %s", peer_id, text.replace('\n', ' '))
    _get_vk().messages.send(
        peer_id=peer_id,
        random_id=get_random_id(),
        message=text
    )


def get_user_name(user_id: int) -> str:
    info = _get_vk().users.get(user_ids=user_id)[0]
    return f"{info['first_name']} {info['last_name']}"


def handle_planka(msg, text: str):
    peer_id = msg["peer_id"]
    user_id = msg["from_id"]

    name = get_user_name(user_id)

    actual_seconds = None
    parts = text.strip().split()
    if len(parts) >= 2 and parts[0].lower() == "планка":
        try:
            actual_seconds = int(parts[1])
        except ValueError:
            actual_seconds = None

    result = db.mark_plank(user_id, name, actual_seconds)
    today_str = db.get_today_date_str()

    if result.is_new:
        if actual_seconds is not None:
            send_message(peer_id, f"{today_str} планка сделана ({actual_seconds})")
        else:
            send_message(peer_id, f"{today_str} планка сделана")
    elif result.was_updated:
        send_message(peer_id, f"планка обновлена ({actual_seconds}) 💪")
    else:
        send_message(peer_id, "планка уже сделана")


def handle_stats(msg):
    peer_id = msg["peer_id"]
    done, not_done = db.get_stats_for_today()

    today_str = db.get_today_date_str()
    text_parts = [f"Стата за {today_str}:"]

    if done:
        text_parts.append("Сделали планку:")
        text_parts.append(", ".join(done))
    else:
        text_parts.append("Сделали планку: никто")

    if not_done:
        text_parts.append("")
        text_parts.append("Не сделали планку:")
        text_parts.append(", ".join(not_done))
    else:
        text_parts.append("")
        text_parts.append("Все отметились или ещё никто не добавлен в базу")

    send_message(peer_id, "\n".join(text_parts))


def handle_guide(msg):
    peer_id = msg["peer_id"]
    text = (
        "Гайд по командам:\n"
        "• планка — отметить, что ты сделал(а) планку сегодня.\n"
        "• планка X — отметить планку с указанием числа секунд X.\n"
        "  Если планка уже записана, значение X обновит результат.\n"
        "• стата — показать, кто сегодня сделал планку и кто нет.\n"
        "• гайд — показать это сообщение.\n"
        "• ебать гусей [контекст] — мудрая история про гусей и планку.\n"
        "• кто сегодня [вопрос] — определить победителя дня по переписке в чате.\n"
        "  Например: кто сегодня больше всех похож на Цоя?\n"
        "• объясни [как] — объяснить приложенное сообщение в нужном стиле.\n"
        "  Ответь на сообщение или перешли его, затем напиши «объясни по-пацански».\n"
        "  Если стиль не указан — выберу сам. Можно переслать несколько сообщений.\n"
    )
    send_message(peer_id, text)


def _call_llm(extra_context: str) -> str:
    """Call Yandex AI Studio (OpenAI-compatible) and return the generated story."""
    client = openai.OpenAI(
        api_key=YANDEX_LLM_API_KEY,
        base_url="https://ai.api.cloud.yandex.net/v1",
        project=YANDEX_FOLDER_ID,
    )
    response = client.responses.create(
        model=f"gpt://{YANDEX_FOLDER_ID}/{DEFAULT_MODEL}",
        temperature=DEFAULT_TEMPERATURE,
        instructions=GEESE_STORY_PROMPT,
        input=extra_context if extra_context else "просто история",
        max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
    )
    return response.output_text


def _build_who_is_today_input(question: str, user_messages: list[tuple[str, list[str]]]) -> str:
    """
    Build the LLM input string for кто сегодня.

    Applies a fair token economy: the total character budget is divided equally
    among all users. Within each user's quota the most-recent messages are kept
    (reversed order, newest first) so that fresh context survives trimming.

    Args:
        question: the raw question text (e.g. "больше всех похож на Цоя")
        user_messages: list of (user_name, [msg_text, ...]) oldest-first

    Returns:
        Formatted string to pass as `input` to the LLM.
    """
    if not user_messages:
        return f"Вопрос: {question}\n\nСообщений в чате за сегодня нет."

    n_users = len(user_messages)
    per_user_budget = _WHO_IS_TODAY_CHAR_BUDGET // n_users

    sections = []
    for name, msgs in user_messages:
        # Take newest messages first until budget is exhausted, then reverse back
        selected: list[str] = []
        remaining = per_user_budget
        for msg in reversed(msgs):
            if remaining <= 0:
                break
            chunk = msg[:remaining]
            selected.append(chunk)
            remaining -= len(chunk)
        selected.reverse()  # restore chronological order

        user_block = "\n".join(f"  — {m}" for m in selected)
        sections.append(f"{name}:\n{user_block}")

    messages_block = "\n\n".join(sections)
    return (
        f"Вопрос: {question}\n\n"
        f"Переписка участников за сегодня:\n\n"
        f"{messages_block}"
    )


def _call_explain_llm(text_to_explain: str, style: str) -> str:
    """Call LLM to explain text_to_explain in the given style."""
    client = openai.OpenAI(
        api_key=YANDEX_LLM_API_KEY,
        base_url="https://ai.api.cloud.yandex.net/v1",
        project=YANDEX_FOLDER_ID,
    )
    llm_input = f"Стиль объяснения: {style}\n\nТекст:\n{text_to_explain}"
    response = client.responses.create(
        model=f"gpt://{YANDEX_FOLDER_ID}/{DEFAULT_MODEL}",
        temperature=DEFAULT_TEMPERATURE,
        instructions=EXPLAIN_PROMPT,
        input=llm_input,
        max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
    )
    return response.output_text


def handle_explain(msg, text_raw: str):
    """
    Handle "объясни [как]" command.

    Extracts the text to explain from reply_message or fwd_messages,
    then calls LLM to explain it in the requested style.
    """
    peer_id = msg["peer_id"]

    # Step 1 — extract text to explain
    source_text = None

    reply = msg.get("reply_message")
    if reply and reply.get("text"):
        source_text = reply["text"]
    else:
        fwd = msg.get("fwd_messages") or []
        texts = [m["text"] for m in fwd if m.get("text")]
        if texts:
            source_text = "\n\n".join(texts)

    if not source_text:
        send_message(
            peer_id,
            "Ответь на сообщение или перешли его, а потом напиши «объясни [как]»."
        )
        return

    # Step 2 — extract style
    trigger = "объясни"
    lower_raw = text_raw.lower()
    idx = lower_raw.find(trigger)
    if idx != -1:
        style = text_raw[idx + len(trigger):].strip()
    else:
        style = ""

    if not style:
        style = random.choice(DEFAULT_EXPLAIN_STYLES)

    logger.info("handle_explain: style=%r source_text=%r", style, source_text[:80])

    # Step 3 — send placeholder, then call LLM
    send_message(peer_id, random.choice(EXPLAIN_PLACEHOLDER_MESSAGES))

    try:
        explanation = _call_explain_llm(source_text, style)
    except Exception as e:
        logger.error("LLM call failed for explain: %s", e)
        send_message(peer_id, "Что-то пошло не так. Попробуй позже.")
        return

    send_message(peer_id, explanation)


def _call_who_is_today_llm(question: str, user_messages: list[tuple[str, list[str]]]) -> str:
    """Call LLM for кто сегодня command."""
    client = openai.OpenAI(
        api_key=YANDEX_LLM_API_KEY,
        base_url="https://ai.api.cloud.yandex.net/v1",
        project=YANDEX_FOLDER_ID,
    )
    llm_input = _build_who_is_today_input(question, user_messages)
    response = client.responses.create(
        model=f"gpt://{YANDEX_FOLDER_ID}/{DEFAULT_MODEL}",
        temperature=DEFAULT_TEMPERATURE,
        instructions=WHO_IS_TODAY_PROMPT,
        input=llm_input,
        max_output_tokens=_WHO_IS_TODAY_MAX_OUTPUT_TOKENS,
    )
    return response.output_text


def handle_geese(msg, text_raw: str):
    """
    Handle the "ебать гусей [extra context]" command.

    1. Immediately dispatch a random placeholder message.
    2. Parse extra context (everything after "ебать гусей").
    3. Call the LLM and send the resulting story.
    """
    peer_id = msg["peer_id"]

    # Step 1 — send placeholder immediately
    send_message(peer_id, random.choice(GEESE_PLACEHOLDER_MESSAGES))

    # Step 2 — extract extra context
    trigger = "ебать гусей"
    lower_raw = text_raw.lower()
    idx = lower_raw.find(trigger)
    if idx != -1:
        extra_context = text_raw[idx + len(trigger):].strip()
    else:
        extra_context = ""

    logger.info("handle_geese: extra_context=%r", extra_context)

    # Step 3 — call LLM and send story
    try:
        story = _call_llm(extra_context)
    except Exception as e:
        logger.error("LLM call failed: %s", e)
        send_message(peer_id, "Гуси молчат. Что-то пошло не так на их стороне.")
        return

    send_message(peer_id, story + "\n\nВы ебете гусей.")


def handle_who_is_today(msg, text_raw: str):
    """
    Handle "кто сегодня [question]" command.

    1. Send a placeholder immediately.
    2. Extract the question (everything after "кто сегодня").
    3. Load today's messages from DB.
    4. Apply token economy and call LLM.
    5. Send the result.
    """
    peer_id = msg["peer_id"]

    # Step 1 — extract question
    trigger = "кто сегодня"
    lower_raw = text_raw.lower()
    idx = lower_raw.find(trigger)
    if idx != -1:
        question = text_raw[idx + len(trigger):].strip()
    else:
        question = ""

    if not question:
        send_message(peer_id, "Укажи вопрос. Например: кто сегодня больше всех похож на Цоя?")
        return

    logger.info("handle_who_is_today: question=%r", question)

    # Step 2 — send placeholder
    send_message(peer_id, random.choice(WHO_IS_TODAY_PLACEHOLDER_MESSAGES))

    # Step 3 — load messages
    try:
        user_messages = db.get_messages_for_today()
    except Exception as e:
        logger.error("Failed to load messages for who_is_today: %s", e)
        send_message(peer_id, "Не удалось загрузить переписку. Попробуй позже.")
        return

    # Step 4 — call LLM
    try:
        verdict = _call_who_is_today_llm(question, user_messages)
    except Exception as e:
        logger.error("LLM call failed for who_is_today: %s", e)
        send_message(peer_id, "Что-то пошло не так при анализе переписки. Попробуй позже.")
        return

    # Step 5 — send result
    send_message(peer_id, verdict)


def process_message(msg):
    text_raw = (msg.get("text") or "").strip()
    text = text_raw.lower()

    if msg.get("peer_id", 0) < 2000000000:
        logger.warning("Ignoring private message from peer_id=%s", msg.get("peer_id"))
        return

    logger.info("Processing message from peer_id=%s: %s", msg.get("peer_id"), text_raw)

    # Track every group chat message (best-effort — never block command handling)
    # Use peer_id + conversation_message_id as the unique key:
    #   - msg["id"] is 0 or unreliable for group chats
    #   - conversation_message_id is a per-conversation sequential counter → globally
    #     unique when combined with peer_id
    parts = text.split()

    user_id = msg.get("from_id")
    peer_id_val = msg.get("peer_id", "")
    conv_msg_id = msg.get("conversation_message_id", "")
    message_id = f"{peer_id_val}_{conv_msg_id}" if (peer_id_val and conv_msg_id) else ""

    # Always ensure user exists in users table (best-effort — never block command handling).
    # Resolving the name once here also reuses it for save_message below.
    _fetched_user_name = None
    if user_id:
        try:
            _fetched_user_name = get_user_name(user_id)
            db.ensure_user(user_id, _fetched_user_name)
        except Exception as e:
            logger.warning("Failed to ensure user in users table: %s", e)

    # Only save organic chat messages — exclude all bot commands.
    # Commands are not real chat content and would skew LLM analysis.
    _is_bot_command = (
        (parts and parts[0] == "планка")
        or text == "стата"
        or text == "гайд"
        or text.startswith("ебать гусей")
        or text.startswith("кто сегодня")
        or text.startswith("объясни")
    )
    if user_id and message_id and text_raw and not _is_bot_command and _fetched_user_name:
        try:
            db.save_message(message_id, user_id, _fetched_user_name, text_raw)
        except Exception as e:
            logger.warning("Failed to save message to chat_messages: %s", e)

    if parts and parts[0] == "планка":
        if len(parts) <= 2:
            handle_planka(msg, text_raw)

    elif text == "стата":
        handle_stats(msg)

    elif text == "гайд":
        handle_guide(msg)

    elif text.startswith("ебать гусей"):
        handle_geese(msg, text_raw)

    elif text.startswith("кто сегодня"):
        handle_who_is_today(msg, text_raw)

    elif text.startswith("объясни"):
        handle_explain(msg, text_raw)

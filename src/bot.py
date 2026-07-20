import hashlib
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
STORY_MODE_PROMPT = _load_prompt("story_mode_prompt.txt")
GOSSIP_PROMPT = _load_prompt("gossip_prompt.txt")
ADVICE_PROMPT = _load_prompt("advice_prompt.txt")
TOAST_PROMPT = _load_prompt("toast_prompt.txt")
HOROSCOPE_PROMPT = _load_prompt("horoscope_prompt.txt")

# ---------------------------------------------------------------------------
# Token economy constants for кто сегодня
# ---------------------------------------------------------------------------
# Model context: 32,768 tokens.
# Reserve ~1,000 for system prompt + instruction overhead, ~500 for output.
# Remaining budget for user messages: ~31,000 tokens.
# Rough estimate: 1 token ≈ 3.5 Russian characters.
_WHO_IS_TODAY_CHAR_BUDGET = 31_000 * 3  # ~93,000 chars total for all users
_WHO_IS_TODAY_MAX_OUTPUT_TOKENS = DEFAULT_MAX_OUTPUT_TOKENS

# Maximum number of most-recent messages shown per user.
# Caps representation so high-volume chatters don't crowd out quiet ones.
_WHO_IS_TODAY_MAX_MSGS_PER_USER = 25

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

# ---------------------------------------------------------------------------
# Token economy constants for сплетня
# ---------------------------------------------------------------------------
# Same model context as who_is_today: 32,768 tokens, ~3 chars/token → 93,000 chars.
# Reserve for system prompt + output overhead; rest split equally among users.
_GOSSIP_CHAR_BUDGET = 31_000 * 3  # ~93,000 chars total
_GOSSIP_MAX_MSGS_PER_USER = 20

# ---------------------------------------------------------------------------
# Token economy constants for story mode
# ---------------------------------------------------------------------------
# Keep turn[0] (the story premise) + as many recent turns as fit in budget.
# Budget: ~80,000 chars ≈ 27k tokens; leaves room for system prompt + output.
_STORY_CHAR_BUDGET = 80_000
_STORY_MAX_OUTPUT_TOKENS = 500

STORY_START_PLACEHOLDER_MESSAGES = [
    "Открываю книгу судеб… история начинается.",
    "Хорошо. Однажды…",
    "Беру перо. Сейчас будет история.",
    "Отлично. Начинаем повествование…",
    "Разворачиваю свиток. Слушайте.",
]

STORY_CONTINUE_PLACEHOLDER_MESSAGES = [
    "Продолжаю…",
    "Следующая глава уже пишется…",
    "Так-так, интересный поворот. Думаю…",
    "Хм, принято. Развиваю мысль…",
    "История живёт. Пишу…",
    "Интригующе. Продолжаем…",
    "Записываю. Сейчас будет продолжение.",
]

ADVICE_PLACEHOLDER_MESSAGES = [
    "Минуту, консультируюсь с высшими силами…",
    "Записываю совет. Сейчас будет мудрость.",
    "Хм. Вопрос серьёзный. Думаю…",
    "Гуру берёт слово. Молчите.",
    "Открываю книгу судеб на нужной странице…",
    "Секунду — связываюсь с Вселенной.",
]

TOAST_PLACEHOLDER_MESSAGES = [
    "Встаю, поднимаю бокал…",
    "Тихо! Сейчас будет тост.",
    "Дайте сказать. Это важно.",
    "Минуточку внимания. Валерий берёт слово.",
    "Все подняли? Сейчас скажу.",
]

HOROSCOPE_PLACEHOLDER_MESSAGES = [
    "Сверяюсь с планетами…",
    "Секунду, читаю звёзды…",
    "Меркурий шепчет. Слушаю…",
    "Открываю астральную карту…",
    "Луна говорит. Записываю.",
    "Космос на связи. Жди.",
]

_ZODIAC_SIGNS = [
    "Овен", "Телец", "Близнецы", "Рак", "Лев", "Дева",
    "Весы", "Скорпион", "Стрелец", "Козерог", "Водолей", "Рыбы",
]


def _get_zodiac_sign(user_id: int, date_str: str) -> str:
    """Deterministic zodiac sign from user_id + date. Same user, same day = same sign."""
    h = hashlib.md5(f"{user_id}:{date_str}".encode()).hexdigest()
    return _ZODIAC_SIGNS[int(h, 16) % 12]


GOSSIP_PLACEHOLDER_MESSAGES = [
    "Бабки на лавке зашептались…",
    "Ой, только никому! Уже собираем слухи…",
    "Слышала? Нет? Сейчас расскажу…",
    "Тихо-тихо, соседка не слышит. Минуту…",
    "Это всё неспроста. Разбираемся…",
    "Та-а-ак, что тут у нас. Сейчас сплетём…",
]

STORY_END_PLACEHOLDER_MESSAGES = [
    "Закрываю книгу. Финал пишется…",
    "Подводим итоги. Последняя страница…",
    "Всё хорошее когда-нибудь заканчивается. Пишу финал…",
    "Завязываю все нити. Момент…",
    "Финальный аккорд. Сейчас будет развязка…",
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
    is_increment = False
    parts = text.strip().split()
    if len(parts) >= 2 and parts[0].lower() == "планка":
        raw_val = parts[1]
        if raw_val.startswith("+"):
            try:
                actual_seconds = int(raw_val[1:])
                is_increment = True
            except ValueError:
                actual_seconds = None
        else:
            try:
                actual_seconds = int(raw_val)
            except ValueError:
                actual_seconds = None

    result = db.mark_plank(user_id, name, actual_seconds, is_increment=is_increment)
    today_str = db.get_today_date_str()

    if result.is_new:
        if actual_seconds is not None:
            send_message(peer_id, f"{today_str} планка сделана ({actual_seconds})")
        else:
            send_message(peer_id, f"{today_str} планка сделана")
    elif result.was_incremented:
        send_message(peer_id, f"планка увеличена (+{actual_seconds}) 💪")
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
        "• планка +X — добавить X секунд к уже записанному времени.\n"
        "  Удобно, если делал(а) планку несколькими подходами.\n"
        "• стата — показать, кто сегодня сделал планку и кто нет.\n"
        "• гайд — показать это сообщение.\n"
        "• ебать гусей [контекст] — мудрая история про гусей и планку.\n"
        "• кто сегодня [вопрос] — определить победителя дня по переписке в чате.\n"
        "  Например: кто сегодня больше всех похож на Цоя?\n"
        "• объясни [как] — объяснить приложенное сообщение в нужном стиле.\n"
        "  Ответь на сообщение или перешли его, затем напиши «объясни по-пацански».\n"
        "  Если стиль не указан — выберу сам. Можно переслать несколько сообщений.\n"
        "• начать историю [тема] — запустить совместную историю в чате.\n"
        "  Бот начинает, а каждое следующее сообщение участников продолжает её.\n"
        "  Остальные команды работают как обычно во время истории.\n"
        "• кончить историю — завершить и удалить текущую историю.\n"
        "  Скачать текущую историю: <адрес бота>/current-story.txt\n"
        "  (спроси у того, кто знает адрес бота; история удаляется после завершения — сохрани заранее!)\n"
        "• сплетня — бабки на лавке разберут переписку за сегодня и сочинят свежие слухи.\n"
        "• совет [тема] — мудрый совет от Великого Гуру Абсурда. Тема необязательна.\n"
        "• тост [повод] — пафосный тост от тамады Валерия. Повод необязателен.\n"
        "• гороскоп — абсурдный гороскоп на сегодня.\n"
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

    Fair representation strategy:
    - Each user is capped at _WHO_IS_TODAY_MAX_MSGS_PER_USER most-recent messages
      so high-volume chatters don't crowd out quieter participants.
    - The remaining per-user char budget is applied as a secondary safety trim
      (handles unusually long individual messages).
    - User order is randomised each call to eliminate LLM positional bias.
    - The total message count for each user is shown so the LLM has explicit
      context about participation level.

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

    # Shuffle to remove alphabetical ordering and eliminate LLM positional bias
    shuffled = list(user_messages)
    random.shuffle(shuffled)

    sections = []
    for name, msgs in shuffled:
        total_count = len(msgs)

        # Cap to most-recent N messages (primary fairness mechanism)
        capped = msgs[-_WHO_IS_TODAY_MAX_MSGS_PER_USER:]

        # Secondary trim: apply char budget (handles very long individual messages)
        selected: list[str] = []
        remaining = per_user_budget
        for msg in reversed(capped):
            if remaining <= 0:
                break
            chunk = msg[:remaining]
            selected.append(chunk)
            remaining -= len(chunk)
        selected.reverse()  # restore chronological order

        user_block = "\n".join(f"  — {m}" for m in selected)
        header = f"{name} ({total_count} сообщ.):"
        sections.append(f"{header}\n{user_block}")

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
    logger.info("_call_who_is_today_llm: llm_input=%r WHO_IS_TODAY_PROMPT=%r", llm_input, WHO_IS_TODAY_PROMPT)
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


# ---------------------------------------------------------------------------
# Story mode helpers and handlers
# ---------------------------------------------------------------------------

def _trim_story_context(turns: list[dict]) -> list[dict]:
    """
    Trim story turns to fit within _STORY_CHAR_BUDGET.

    Strategy:
    - Always keep turns[0] (the initial story premise / начать историю line).
    - Fill the remaining budget with as many of the MOST RECENT turns as possible.
    - If there is only one turn, return it as-is.

    Returns a list of turns in chronological order ready to pass to the LLM.
    """
    if len(turns) <= 1:
        return list(turns)

    first_turn = turns[0]
    rest = turns[1:]

    remaining_budget = _STORY_CHAR_BUDGET - len(first_turn["content"])

    # Walk from newest to oldest, accumulating turns that fit
    selected_rest: list[dict] = []
    for turn in reversed(rest):
        cost = len(turn["content"])
        if remaining_budget <= 0:
            break
        selected_rest.append(turn)
        remaining_budget -= cost

    selected_rest.reverse()  # restore chronological order
    return [first_turn] + selected_rest


def _call_story_llm(turns: list[dict]) -> str:
    """
    Call Yandex AI Studio with full multi-turn chat history for story mode.

    Uses chat.completions.create (multi-turn) instead of responses.create (single-turn)
    so the LLM sees the full conversation thread.
    """
    client = openai.OpenAI(
        api_key=YANDEX_LLM_API_KEY,
        base_url="https://ai.api.cloud.yandex.net/v1",
        project=YANDEX_FOLDER_ID,
    )
    messages = [{"role": "system", "content": STORY_MODE_PROMPT}] + turns
    response = client.chat.completions.create(
        model=f"gpt://{YANDEX_FOLDER_ID}/{DEFAULT_MODEL}",
        temperature=DEFAULT_TEMPERATURE,
        messages=messages,
        max_tokens=_STORY_MAX_OUTPUT_TOKENS,
    )
    return response.choices[0].message.content


def handle_start_story(msg, text_raw: str):
    """
    Handle "начать историю [тема]" command.

    1. Clear any existing story for this chat (restart).
    2. Save the user's opening prompt as turn[0] (role=user).
    3. Call LLM to generate the opening line.
    4. Save the bot's reply as turn[1] (role=assistant).
    5. Send the opening line to chat.
    """
    peer_id = msg["peer_id"]

    # Extract optional theme (everything after "начать историю")
    trigger = "начать историю"
    lower_raw = text_raw.lower()
    idx = lower_raw.find(trigger)
    user_prompt = text_raw[idx + len(trigger):].strip() if idx != -1 else ""
    if not user_prompt:
        user_prompt = "начать историю"

    logger.info("handle_start_story: peer_id=%s prompt=%r", peer_id, user_prompt)

    # Clear any existing story for this chat
    try:
        db.story_clear(peer_id)
    except Exception as e:
        logger.warning("Failed to clear existing story: %s", e)

    # Send placeholder immediately
    send_message(peer_id, random.choice(STORY_START_PLACEHOLDER_MESSAGES))

    # Seed the first user turn
    first_turn = {"role": "user", "content": user_prompt}
    try:
        db.story_append_turns(peer_id, [first_turn])
    except Exception as e:
        logger.error("Failed to save story first turn: %s", e)
        send_message(peer_id, "Не удалось начать историю. Попробуй позже.")
        return

    # Call LLM with just the first turn
    try:
        opening = _call_story_llm([first_turn])
    except Exception as e:
        logger.error("LLM call failed for story start: %s", e)
        send_message(peer_id, "Не удалось начать историю. Попробуй позже.")
        return

    # Save bot reply
    bot_turn = {"role": "assistant", "content": opening}
    try:
        db.story_append_turns(peer_id, [bot_turn])
    except Exception as e:
        logger.warning("Failed to save story bot turn: %s", e)

    send_message(peer_id, opening)


def handle_continue_story(msg, text_raw: str):
    """
    Advance an active story with a new user message.

    1. Load existing turns from DB.
    2. Append the new user message (in memory only for building context).
    3. Trim context to fit token budget.
    4. Call LLM.
    5. Persist the new user + bot turns to DB.
    6. Send bot reply to chat.
    """
    peer_id = msg["peer_id"]
    user_name = None
    if msg.get("from_id") and hasattr(msg, "__contains__") and "_fetched_user_name" in msg:
        user_name = msg["_fetched_user_name"]

    logger.info("handle_continue_story: peer_id=%s text=%r", peer_id, text_raw[:80])

    # Load existing turns
    try:
        turns = db.story_get_turns(peer_id)
    except Exception as e:
        logger.error("Failed to load story turns: %s", e)
        return

    if not turns:
        # Story expired or was cleared — nothing to continue
        return

    new_user_turn = {"role": "user", "content": text_raw}
    context = _trim_story_context(turns + [new_user_turn])

    # Send placeholder immediately
    send_message(peer_id, random.choice(STORY_CONTINUE_PLACEHOLDER_MESSAGES))

    # Call LLM
    try:
        continuation = _call_story_llm(context)
    except Exception as e:
        logger.error("LLM call failed for story continuation: %s", e)
        send_message(peer_id, "История прервалась. Попробуй ещё раз.")
        return

    # Persist both turns
    bot_turn = {"role": "assistant", "content": continuation}
    try:
        db.story_append_turns(peer_id, [new_user_turn, bot_turn])
    except Exception as e:
        logger.warning("Failed to save story turns: %s", e)

    send_message(peer_id, continuation)


def handle_end_story(msg):
    """
    Handle "кончить историю" command.

    1. Check if story is active; if not, inform the user.
    2. Load existing turns and append a wrap-up user turn.
    3. Call LLM with a signal to conclude the story.
    4. Clear all turns from DB.
    5. Send the final paragraph.
    """
    peer_id = msg["peer_id"]

    logger.info("handle_end_story: peer_id=%s", peer_id)

    # Check if story is active
    try:
        active = db.story_is_active(peer_id)
    except Exception as e:
        logger.error("Failed to check story active status: %s", e)
        send_message(peer_id, "Не удалось проверить статус истории. Попробуй позже.")
        return

    if not active:
        send_message(peer_id, "Истории сейчас нет. Начни новую командой «начать историю».")
        return

    # Load existing turns
    try:
        turns = db.story_get_turns(peer_id)
    except Exception as e:
        logger.error("Failed to load story turns for ending: %s", e)
        send_message(peer_id, "Не удалось завершить историю. Попробуй позже.")
        return

    # Send placeholder immediately
    send_message(peer_id, random.choice(STORY_END_PLACEHOLDER_MESSAGES))

    # Append wrap-up signal
    end_turn = {"role": "user", "content": "кончить историю"}
    context = _trim_story_context(turns + [end_turn])

    # Call LLM
    try:
        finale = _call_story_llm(context)
    except Exception as e:
        logger.error("LLM call failed for story ending: %s", e)
        send_message(peer_id, "Не удалось завершить историю. Попробуй позже.")
        return

    # Clear the story
    try:
        db.story_clear(peer_id)
    except Exception as e:
        logger.warning("Failed to clear story after ending: %s", e)

    send_message(peer_id, finale)


def handle_advice(msg, text_raw: str):
    """
    Handle "совет [про что]" command.

    1. Send placeholder immediately.
    2. Extract optional topic (everything after "совет").
    3. Call LLM with advice prompt.
    4. Send result.
    """
    peer_id = msg["peer_id"]

    trigger = "совет"
    lower_raw = text_raw.lower()
    idx = lower_raw.find(trigger)
    if idx != -1:
        topic = text_raw[idx + len(trigger):].strip()
    else:
        topic = ""

    llm_input = (
        f"Дай АБСУРДНЫЙ, БРЕДОВЫЙ совет (2-3 предложения чистым текстом, БЕЗ фактов, БЕЗ списков, БЕЗ маркдауна). "
        f"Тема: {topic}"
        if topic
        else "Дай АБСУРДНЫЙ, БРЕДОВЫЙ жизненный совет (2-3 предложения чистым текстом, БЕЗ фактов, БЕЗ списков, БЕЗ маркдауна). Тема на твой выбор."
    )
    logger.info("handle_advice: topic=%r", topic)

    send_message(peer_id, random.choice(ADVICE_PLACEHOLDER_MESSAGES))

    client = openai.OpenAI(
        api_key=YANDEX_LLM_API_KEY,
        base_url="https://ai.api.cloud.yandex.net/v1",
        project=YANDEX_FOLDER_ID,
    )
    try:
        response = client.responses.create(
            model=f"gpt://{YANDEX_FOLDER_ID}/{DEFAULT_MODEL}",
            temperature=DEFAULT_TEMPERATURE,
            instructions=ADVICE_PROMPT,
            input=llm_input,
            max_output_tokens=200,
        )
        send_message(peer_id, response.output_text)
    except Exception as e:
        logger.error("LLM call failed for advice: %s", e)
        send_message(peer_id, "Гуру недоступен. Попробуй позже.")


def handle_toast(msg, text_raw: str):
    """
    Handle "тост [за что]" command.

    1. Send placeholder immediately.
    2. Extract optional occasion (everything after "тост").
    3. Call LLM with toast prompt.
    4. Send result.
    """
    peer_id = msg["peer_id"]

    trigger = "тост"
    lower_raw = text_raw.lower()
    idx = lower_raw.find(trigger)
    if idx != -1:
        occasion = text_raw[idx + len(trigger):].strip()
    else:
        occasion = ""

    llm_input = (
        f"Произнеси АБСУРДНЫЙ, смешной тост тамады Валерия (3-5 предложений чистым текстом, БЕЗ списков, БЕЗ маркдауна, заканчивай призывом выпить). "
        f"Повод: {occasion}"
        if occasion
        else "Произнеси АБСУРДНЫЙ, смешной тост тамады Валерия (3-5 предложений чистым текстом, БЕЗ списков, БЕЗ маркдауна, заканчивай призывом выпить). Повод на твой выбор."
    )
    logger.info("handle_toast: occasion=%r", occasion)

    send_message(peer_id, random.choice(TOAST_PLACEHOLDER_MESSAGES))

    client = openai.OpenAI(
        api_key=YANDEX_LLM_API_KEY,
        base_url="https://ai.api.cloud.yandex.net/v1",
        project=YANDEX_FOLDER_ID,
    )
    try:
        response = client.responses.create(
            model=f"gpt://{YANDEX_FOLDER_ID}/{DEFAULT_MODEL}",
            temperature=DEFAULT_TEMPERATURE,
            instructions=TOAST_PROMPT,
            input=llm_input,
            max_output_tokens=250,
        )
        send_message(peer_id, response.output_text)
    except Exception as e:
        logger.error("LLM call failed for toast: %s", e)
        send_message(peer_id, "Валерий охрип. Попробуй позже.")


def handle_horoscope(msg):
    """
    Handle "гороскоп" command.

    1. Send placeholder immediately.
    2. Derive a deterministic zodiac sign from user_id + today's date.
    3. Call LLM with horoscope prompt (sign is in the input, NOT in the output).
    4. Send result.
    """
    peer_id = msg["peer_id"]
    user_id = msg["from_id"]

    logger.info("handle_horoscope: peer_id=%s user_id=%s", peer_id, user_id)

    send_message(peer_id, random.choice(HOROSCOPE_PLACEHOLDER_MESSAGES))

    today_str = db.get_today_date_str()
    sign = _get_zodiac_sign(user_id, today_str)

    llm_input = (
        f"Составь АБСУРДНЫЙ гороскоп на сегодня (2-3 предложения чистым текстом, "
        f"БЕЗ маркдауна, БЕЗ списков). "
        f"Внутренний знак (НЕ упоминай его в ответе): {sign}."
    )

    client = openai.OpenAI(
        api_key=YANDEX_LLM_API_KEY,
        base_url="https://ai.api.cloud.yandex.net/v1",
        project=YANDEX_FOLDER_ID,
    )
    try:
        response = client.responses.create(
            model=f"gpt://{YANDEX_FOLDER_ID}/{DEFAULT_MODEL}",
            temperature=DEFAULT_TEMPERATURE,
            instructions=HOROSCOPE_PROMPT,
            input=llm_input,
            max_output_tokens=200,
        )
        send_message(peer_id, response.output_text)
    except Exception as e:
        logger.error("LLM call failed for horoscope: %s", e)
        send_message(peer_id, "Звёзды молчат. Попробуй позже.")


def _build_gossip_input(user_messages: list[tuple[str, list[str]]]) -> str:
    """
    Build LLM input for the gossip (сплетня) command.

    Token economy strategy (mirrors _build_who_is_today_input):
    - Each user is capped at _GOSSIP_MAX_MSGS_PER_USER most-recent messages.
    - Total char budget is divided equally among N users.
    - Within each user's share, newest messages are kept first (secondary trim
      handles unusually long individual messages).
    """
    if not user_messages:
        return "Переписки за сегодня нет."

    n_users = len(user_messages)
    per_user_budget = _GOSSIP_CHAR_BUDGET // n_users

    sections = []
    for name, msgs in user_messages:
        # Primary cap: most-recent N messages
        capped = msgs[-_GOSSIP_MAX_MSGS_PER_USER:]

        # Secondary trim: char budget (handles very long individual messages)
        selected: list[str] = []
        remaining = per_user_budget
        for msg in reversed(capped):
            if remaining <= 0:
                break
            chunk = msg[:remaining]
            selected.append(chunk)
            remaining -= len(chunk)
        selected.reverse()  # restore chronological order

        user_block = "\n".join(f"  — {m}" for m in selected)
        sections.append(f"{name}:\n{user_block}")

    messages_block = "\n\n".join(sections)
    return f"Вот переписка из чата. Сочини сплетни на её основе:\n\n{messages_block}"


def _call_gossip_llm(user_messages: list[tuple[str, list[str]]]) -> str:
    """Call LLM to generate gossip based on today's chat messages."""
    client = openai.OpenAI(
        api_key=YANDEX_LLM_API_KEY,
        base_url="https://ai.api.cloud.yandex.net/v1",
        project=YANDEX_FOLDER_ID,
    )
    llm_input = _build_gossip_input(user_messages)
    logger.info("_call_gossip_llm: llm_input=%r GOSSIP_PROMPT=%r", llm_input, GOSSIP_PROMPT)
    response = client.responses.create(
        model=f"gpt://{YANDEX_FOLDER_ID}/{DEFAULT_MODEL}",
        temperature=DEFAULT_TEMPERATURE,
        instructions=GOSSIP_PROMPT,
        input=llm_input,
        max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
    )
    result = response.output_text
    logger.info("_call_gossip_llm: result=%r", result)
    return result


def handle_gossip(msg):
    """
    Handle "сплетня" command.

    1. Send placeholder immediately.
    2. Load today's messages from DB.
    3. Call LLM with gossip prompt.
    4. Send result.
    """
    peer_id = msg["peer_id"]

    logger.info("handle_gossip: peer_id=%s", peer_id)

    # Send placeholder immediately
    send_message(peer_id, random.choice(GOSSIP_PLACEHOLDER_MESSAGES))

    # Load today's messages
    try:
        user_messages = db.get_messages_for_today()
    except Exception as e:
        logger.error("Failed to load messages for gossip: %s", e)
        send_message(peer_id, "Не удалось достать переписку. Бабки расстроены.")
        return

    if not user_messages:
        send_message(peer_id, "Бабки молчат — сегодня тихо, никто ничего не писал.")
        return

    # Call LLM
    try:
        gossip = _call_gossip_llm(user_messages)
    except Exception as e:
        logger.error("LLM call failed for gossip: %s", e)
        send_message(peer_id, "Бабки охрипли. Что-то пошло не так.")
        return

    send_message(peer_id, gossip)


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
        or text == "сплетня"
        or text.startswith("ебать гусей")
        or text.startswith("кто сегодня")
        or text.startswith("объясни")
        or text.startswith("начать историю")
        or text.startswith("кончить историю")
        or text.startswith("совет")
        or text.startswith("тост")
        or text == "гороскоп"
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

    elif text.startswith("начать историю"):
        handle_start_story(msg, text_raw)

    elif text.startswith("совет"):
        handle_advice(msg, text_raw)

    elif text.startswith("тост"):
        handle_toast(msg, text_raw)

    elif text == "гороскоп":
        handle_horoscope(msg)

    elif text == "сплетня":
        handle_gossip(msg)

    elif text.startswith("кончить историю"):
        handle_end_story(msg)

    # Story continuation runs in parallel for any organic (non-command) message
    # while a story is active. Does not interfere with command routing above.
    if not _is_bot_command and text_raw:
        try:
            if db.story_is_active(peer_id_val):
                handle_continue_story(msg, text_raw)
        except Exception as e:
            logger.warning("Story continuation check/run failed: %s", e)

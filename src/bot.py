import logging
import os
import random
import vk_api
from vk_api.utils import get_random_id
from datetime import date

import openai

from config import VK_GROUP_TOKEN, YANDEX_FOLDER_ID, YANDEX_LLM_API_KEY

logging.getLogger().setLevel(logging.DEBUG)
logging.getLogger(__name__).setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Load the geese story system prompt once at module import time.
# In the deployed function the file lives at prompts/geese_story_prompt.txt
# relative to the working directory; fall back to the repo path for tests.
# ---------------------------------------------------------------------------
_PROMPT_PATHS = [
    os.path.join(os.path.dirname(__file__), "prompts", "geese_story_prompt.txt"),
    os.path.join(os.path.dirname(__file__), "..", "src", "prompts", "geese_story_prompt.txt"),
]
GEESE_STORY_PROMPT = ""
for _p in _PROMPT_PATHS:
    if os.path.exists(_p):
        with open(_p, encoding="utf-8") as _f:
            GEESE_STORY_PROMPT = _f.read().strip()
        break

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

def _get_vk():
    vk_session = vk_api.VkApi(token=VK_GROUP_TOKEN)
    return vk_session.get_api()


def send_message(peer_id, text):
    logger.warning("Sending message to peer_id=%s: %s", peer_id, text)
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

    plank_value = None

    parts = text.strip().split()
    if len(parts) >= 2 and parts[0].lower() == "планка":
        plank_value = parts[1]

    today_str = date.today().isoformat()

    if plank_value is not None:
        send_message(peer_id, f"{today_str} планка сделана ({plank_value})")
    else:
        send_message(peer_id, f"{today_str} планка сделана")


def handle_stats(msg):
    peer_id = msg["peer_id"]
    send_message(peer_id, "Статистика временно недоступна")


def handle_guide(msg):
    peer_id = msg["peer_id"]
    text = (
        "Гайд по командам:\n"
        "• планка — отметить, что ты сделал(а) планку сегодня.\n"
        "• планка X — отметить планку с указанием числа X (выводится в скобках, без единиц измерения).\n"
        "• стата — показать, кто сегодня сделал планку и кто нет.\n"
        "• гайд — показать это сообщение.\n"
        "• ебать гусей [контекст] — мудрая история про гусей и планку.\n"
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
        model=f"gpt://{YANDEX_FOLDER_ID}/yandexgpt-lite/latest",
        temperature=0.8,
        instructions=GEESE_STORY_PROMPT,
        input=extra_context if extra_context else "просто история",
        max_output_tokens=500,
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

    logger.warning("handle_geese: extra_context=%r", extra_context)

    # Step 3 — call LLM and send story
    try:
        story = _call_llm(extra_context)
    except Exception as e:
        logger.error("LLM call failed: %s", e)
        send_message(peer_id, "Гуси молчат. Что-то пошло не так на их стороне.")
        return

    send_message(peer_id, story + "\n\nВы ебете гусей.")


def process_message(msg):
    text_raw = (msg.get("text") or "").strip()
    text = text_raw.lower()

    if msg.get("peer_id", 0) < 2000000000:
        logger.warning("Ignoring private message from peer_id=%s", msg.get("peer_id"))
        return

    logger.warning("Processing message from peer_id=%s: %s", msg.get("peer_id"), text_raw)

    parts = text.split()

    if parts and parts[0] == "планка":
        if len(parts) <= 2:
            handle_planka(msg, text_raw)

    elif text == "стата":
        handle_stats(msg)

    elif text == "гайд":
        handle_guide(msg)

    elif text.startswith("ебать гусей"):
        handle_geese(msg, text_raw)
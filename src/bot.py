import logging
import vk_api
from vk_api.utils import get_random_id
from datetime import date

from config import VK_GROUP_TOKEN

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

vk_session = vk_api.VkApi(token=VK_GROUP_TOKEN)
vk = vk_session.get_api()


def send_message(peer_id, text):
    logger.warning("Sending message to peer_id=%s: %s", peer_id, text)
    vk.messages.send(
        peer_id=peer_id,
        random_id=get_random_id(),
        message=text
    )


def get_user_name(user_id: int) -> str:
    info = vk.users.get(user_ids=user_id)[0]
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
        "• ебать гусей — специальная команда.\n"
    )
    send_message(peer_id, text)


def handle_geese(msg):
    peer_id = msg["peer_id"]
    send_message(peer_id, "Вы ебете гусей из яндекс облака с рабочим пайплайном тест/деплой")


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

    elif text == "ебать гусей":
        handle_geese(msg)
import logging
import random
import vk_api
from vk_api.utils import get_random_id
from datetime import date

from config import VK_GROUP_TOKEN

logging.getLogger().setLevel(logging.DEBUG)
logging.getLogger(__name__).setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)

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
        "• ебать гусей — специальная команда.\n"
    )
    send_message(peer_id, text)


GOOSEFUCK_JOKES = [
    "Гусь подходит к программисту и говорит: «Га-га-га». Программист отвечает: «Сам иди в облако». Вы ебете гусей",
    "— Почему гуси не пишут юнит-тесты? — Потому что им и так всё га-га-рантировано. Вы ебете гусей",
    "Девопс поднял гуся в прод. Гусь упал. Девопс сказал: «Работало же на локалке». Вы ебете гусей",
    "— Сколько гусей нужно, чтобы вкрутить лампочку? — Один, но пайплайн сломается. Вы ебете гусей",
    "Гусь посмотрел в Kubernetes и сказал: «Я думал, только у нас в стае так сложно». Вы ебете гусей",
    "— Как называется гусь в яндекс облаке? — Serverless waterfowl. Вы ебете гусей",
    "Гусь прочитал README и всё равно ничего не понял. Как джун. Вы ебете гусей",
    "— Чем отличается гусь от хорошего кода? — Гусь хотя бы иногда молчит. Вы ебете гусей",
    "Менеджер попросил гуся сделать оценку задачи. Гусь ответил: «2 га-га недели». Вы ебете гусей",
    "Гусь задеплоился в пятницу вечером. В понедельник его уже не было. Вы ебете гусей",
]


def handle_geese(msg):
    peer_id = msg["peer_id"]
    send_message(peer_id, random.choice(GOOSEFUCK_JOKES))


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
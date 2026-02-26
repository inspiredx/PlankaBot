import vk_api
from vk_api.utils import get_random_id
from datetime import date
from flask import Flask, request, abort

from config import VK_GROUP_TOKEN, VK_CONFIRMATION_TOKEN, CALLBACK_PORT
from db import init_db, mark_plank, get_stats_for_today

app = Flask(__name__)

vk_session = vk_api.VkApi(token=VK_GROUP_TOKEN)
vk = vk_session.get_api()


def send_message(peer_id, text):
    vk.messages.send(
        peer_id=peer_id,
        random_id=get_random_id(),
        message=text
    )


def get_user_name(user_id: int) -> str:
    info = vk.users.get(user_ids=user_id)[0]
    return f"{info['first_name']} {info['last_name']}"


def handle_planka(msg, text: str):
    user_id = msg["from_id"]
    peer_id = msg["peer_id"]

    name = get_user_name(user_id)

    plank_value = None

    parts = text.strip().split()
    if len(parts) >= 2 and parts[0].lower() == "планка":
        plank_value = parts[1]

    first_today = mark_plank(user_id, name, plank_value)
    today_str = date.today().isoformat()

    if first_today:
        if plank_value is not None:
            send_message(peer_id, f"{today_str} планка сделана ({plank_value})")
        else:
            send_message(peer_id, f"{today_str} планка сделана")
    else:
        if plank_value is not None:
            send_message(peer_id, f"планка уже сделана ({plank_value})")
        else:
            send_message(peer_id, "планка уже сделана")


def handle_stats(msg):
    peer_id = msg["peer_id"]
    done, not_done = get_stats_for_today()

    today_str = date.today().isoformat()
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
        "• планка X — отметить планку с указанием числа X (выводится в скобках, без единиц измерения).\n"
        "• стата — показать, кто сегодня сделал планку и кто нет.\n"
        "• гайд — показать это сообщение.\n"
        "• ебать гусей — специальная команда.\n"
    )
    send_message(peer_id, text)


def handle_geese(msg):
    peer_id = msg["peer_id"]
    send_message(peer_id, "Вы ебете гусей")


def process_message(msg):
    text_raw = (msg.get("text") or "").strip()
    text = text_raw.lower()

    if msg.get("peer_id", 0) < 2000000000:
        return

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


@app.route("/", methods=["POST"])
def callback():
    data = request.get_json(silent=True)
    if data is None:
        abort(400)

    event_type = data.get("type")

    if event_type == "confirmation":
        return VK_CONFIRMATION_TOKEN, 200

    if event_type == "message_new":
        msg = data.get("object", {}).get("message", {})
        print(data)
        process_message(msg)

    return "ok", 200


if __name__ == "__main__":
    init_db()
    print("Бот запущен (callback)")
    app.run(host="0.0.0.0", port=CALLBACK_PORT)
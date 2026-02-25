import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
from vk_api.utils import get_random_id
from datetime import date

from config import VK_GROUP_TOKEN, VK_GROUP_ID
from db import init_db, mark_plank, get_stats_for_today


def send_message(vk, peer_id, text):
    vk.messages.send(
        peer_id=peer_id,
        random_id=get_random_id(),
        message=text
    )


def get_user_name(vk, user_id: int) -> str:
    info = vk.users.get(user_ids=user_id)[0]
    return f"{info['first_name']} {info['last_name']}"


def handle_planka(vk, event, text: str):
    user_id = event.obj.message["from_id"]
    peer_id = event.obj.message["peer_id"]

    name = get_user_name(vk, user_id)

    plank_value = None

    parts = text.strip().split()
    if len(parts) >= 2 and parts[0].lower() == "планка":
        plank_value = parts[1]

    first_today = mark_plank(user_id, name, plank_value)
    today_str = date.today().isoformat()

    if first_today:
        if plank_value is not None:
            send_message(vk, peer_id, f"{today_str} планка сделана ({plank_value})")
        else:
            send_message(vk, peer_id, f"{today_str} планка сделана")
    else:
        if plank_value is not None:
            send_message(vk, peer_id, f"планка уже сделана ({plank_value})")
        else:
            send_message(vk, peer_id, "планка уже сделана")


def handle_stats(vk, event):
    peer_id = event.obj.message["peer_id"]
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

    send_message(vk, peer_id, "\n".join(text_parts))


def handle_guide(vk, event):
    peer_id = event.obj.message["peer_id"]
    text = (
        "Гайд по командам:\n"
        "• планка — отметить, что ты сделал(а) планку сегодня.\n"
        "• планка X — отметить планку с указанием числа X (выводится в скобках, без единиц измерения).\n"
        "• стата — показать, кто сегодня сделал планку и кто нет.\n"
        "• гайд — показать это сообщение.\n"
        "• ебать гусей — специальная команда.\n"
    )
    send_message(vk, peer_id, text)


def handle_geese(vk, event):
    peer_id = event.obj.message["peer_id"]
    send_message(vk, peer_id, "Вы ебете гусей")


def main():
    init_db()

    vk_session = vk_api.VkApi(token=VK_GROUP_TOKEN)
    vk = vk_session.get_api()
    longpoll = VkBotLongPoll(vk_session, VK_GROUP_ID)

    print("Бот запущен")

    for event in longpoll.listen():
        if event.type != VkBotEventType.MESSAGE_NEW:
            continue

        msg = event.obj.message
        text_raw = (msg.get("text") or "").strip()
        text = text_raw.lower()

        if msg.get("peer_id", 0) < 2000000000:
            continue

        parts = text.split()

        if parts and parts[0] == "планка":
            if len(parts) == 1:
                handle_planka(vk, event, text_raw)
            elif len(parts) == 2:
                handle_planka(vk, event, text_raw)
            else:
                continue

        elif text == "стата":
            handle_stats(vk, event)

        elif text == "гайд":
            handle_guide(vk, event)

        elif text == "ебать гусей":
            handle_geese(vk, event)


if __name__ == "__main__":
    main()

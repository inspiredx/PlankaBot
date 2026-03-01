import os
import logging

logging.getLogger().setLevel(logging.INFO)

VK_GROUP_TOKEN = os.getenv("VK_GROUP_TOKEN")
VK_CONFIRMATION_TOKEN = os.getenv("VK_CONFIRMATION_TOKEN")
VK_SECRET_KEY = os.environ["VK_SECRET_KEY"]

YANDEX_FOLDER_ID = os.getenv("YANDEX_FOLDER_ID", "")
YANDEX_LLM_API_KEY = os.getenv("YANDEX_LLM_API_KEY", "")

YDB_ENDPOINT = os.getenv("YDB_ENDPOINT", "")
YDB_DATABASE = os.getenv("YDB_DATABASE", "")

PLANK_TIMEZONE = os.getenv("PLANK_TIMEZONE", "Europe/Moscow")
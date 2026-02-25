import os

VK_GROUP_TOKEN = os.getenv("VK_GROUP_TOKEN")
VK_GROUP_ID = os.getenv("VK_GROUP_ID")

if not VK_GROUP_TOKEN or not VK_GROUP_ID:
    raise RuntimeError("Переменные не заданы")

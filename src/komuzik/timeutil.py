from datetime import datetime
from zoneinfo import ZoneInfo

MSK = ZoneInfo("Europe/Moscow")


def today_msk() -> str:
    return datetime.now(MSK).strftime("%Y-%m-%d")

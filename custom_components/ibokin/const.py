"""Stałe integracji IBOKIN (nieoficjalna integracja IBO Niepołomice)."""
from datetime import timedelta

DOMAIN = "ibokin"
MANUFACTURER = "IBOKIN / IBO Infrastruktura Niepołomice"

BASE_URL = "https://ibok.infrastruktura.eu"
LOGIN_URL = BASE_URL + "/client/Login.aspx?ReturnUrl=%2fclient%2f"
URL_STREFA = BASE_URL + "/client/"
URL_HISTORIA = BASE_URL + "/client/HistoriaOdczytu.aspx?id={meter_id}"
URL_NIEZAPLACONE = BASE_URL + "/client/NiezaplaconePlatnosci.aspx"

CONF_METER_ID = "meter_id"
DEFAULT_METER_ID = ""
DEFAULT_SCAN_INTERVAL = timedelta(hours=12)
REQUEST_TIMEOUT = 60

LOGIN_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

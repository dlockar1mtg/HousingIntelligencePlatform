import json
import os
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
INPUT_DIR = BASE_DIR / "inputs"
OUTPUT_DIR = BASE_DIR / "outputs"
CACHE_DIR = BASE_DIR / "cache"
LOG_DIR = BASE_DIR / "logs"
CONFIG_DIR = BASE_DIR / "config"

for path in [INPUT_DIR, OUTPUT_DIR, CACHE_DIR, LOG_DIR, CONFIG_DIR]:
    path.mkdir(exist_ok=True)

def log(message: str) -> None:
    print(message, flush=True)

def load_settings() -> dict:
    path = CONFIG_DIR / "settings.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))

def get_census_api_key() -> str:
    env = os.environ.get("CENSUS_API_KEY", "").strip()
    if env:
        return env
    return load_settings().get("census_api_key", "").strip()

def clean_name(value) -> str:
    if value is None:
        return ""
    value = str(value).strip().lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value
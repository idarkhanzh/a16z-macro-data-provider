"""Environment variable settings. Values are secrets: never log them."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

ALL_VARS = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_IDS", "BLS_API_KEY")

_CHAT_ID = re.compile(r"^(-?\d+|@[A-Za-z][A-Za-z0-9_]{4,31})$")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str = field(default="", repr=False)
    telegram_chat_ids: tuple[str, ...] = ()
    bls_api_key: str = field(default="", repr=False)

    def secrets(self) -> list[str]:
        return [s for s in (self.telegram_bot_token, self.bls_api_key) if s]


def parse_chat_ids(raw: str) -> tuple[str, ...]:
    """Parse "123456789, -1001234567890" into ("123456789", "-1001234567890").

    Accepts private chat and group IDs, -100... supergroup/channel IDs and
    @channelusername. Whitespace is trimmed; duplicates are dropped.
    """
    ids = [part.strip() for part in raw.split(",") if part.strip()]
    if not ids:
        raise ConfigError("TELEGRAM_CHAT_IDS is empty; expected e.g. 123456789 or 123456789,-1001234567890")
    bad = [i for i in ids if not _CHAT_ID.match(i)]
    if bad:
        raise ConfigError(f"TELEGRAM_CHAT_IDS has invalid entries: {', '.join(bad)} (expected numeric IDs, comma-separated)")
    return tuple(dict.fromkeys(ids))


def load_settings(env: Mapping[str, str] | None = None, required: Sequence[str] = ALL_VARS) -> Settings:
    """Read settings from the environment, failing fast if a required variable is missing."""
    env = os.environ if env is None else env
    values = {name: env.get(name, "").strip() for name in ALL_VARS}
    missing = [name for name in required if not values[name]]
    if missing:
        raise ConfigError(f"Missing required environment variable(s): {', '.join(missing)}. See .env.example.")
    raw_ids = values["TELEGRAM_CHAT_IDS"]
    return Settings(
        telegram_bot_token=values["TELEGRAM_BOT_TOKEN"],
        telegram_chat_ids=parse_chat_ids(raw_ids) if raw_ids else (),
        bls_api_key=values["BLS_API_KEY"],
    )


def load_dotenv(path: str | Path = ".env") -> None:
    """Load KEY=VALUE lines from a local .env file (for local runs; Railway has none).

    Variables already set in the environment win.
    """
    path = Path(path)
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        text = raw.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, _, value = text.removeprefix("export ").partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        os.environ.setdefault(key, value)

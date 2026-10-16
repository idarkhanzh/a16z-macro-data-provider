import os

import pytest

from macro_bot.settings import ConfigError, load_dotenv, load_settings, parse_chat_ids

FULL_ENV = {
    "TELEGRAM_BOT_TOKEN": "123:secret-token",
    "TELEGRAM_CHAT_IDS": "123456789",
    "BLS_API_KEY": "secret-key",
}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("123456789", ("123456789",)),
        ("123456789,-1001234567890", ("123456789", "-1001234567890")),
        ("  123456789 ,  -1001234567890  ", ("123456789", "-1001234567890")),
        ("-987654321", ("-987654321",)),  # basic group
        ("123456789,,123456789,", ("123456789",)),  # empty parts and duplicates dropped
        ("@my_channel", ("@my_channel",)),
    ],
)
def test_parse_chat_ids(raw, expected):
    assert parse_chat_ids(raw) == expected


@pytest.mark.parametrize("raw", ["", " , ", "abc", "123;456", "12 34", "-100abc"])
def test_parse_chat_ids_rejects_bad_input(raw):
    with pytest.raises(ConfigError):
        parse_chat_ids(raw)


def test_load_settings_ok():
    settings = load_settings({**FULL_ENV, "TELEGRAM_CHAT_IDS": " 1, -1001234567890 "})
    assert settings.telegram_chat_ids == ("1", "-1001234567890")
    assert settings.bls_api_key == "secret-key"


def test_missing_vars_listed_without_leaking_values():
    with pytest.raises(ConfigError) as err:
        load_settings({"TELEGRAM_BOT_TOKEN": "123:secret-token", "BLS_API_KEY": "  "})
    message = str(err.value)
    assert "TELEGRAM_CHAT_IDS" in message and "BLS_API_KEY" in message
    assert "TELEGRAM_BOT_TOKEN" not in message
    assert "secret" not in message


def test_dry_run_needs_only_bls_key():
    settings = load_settings({"BLS_API_KEY": "k"}, required=("BLS_API_KEY",))
    assert settings.telegram_chat_ids == ()


def test_repr_hides_secrets():
    text = repr(load_settings(FULL_ENV))
    assert "secret" not in text


def test_load_dotenv_does_not_override(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text('# comment\nMB_TEST_A="from file"\nexport MB_TEST_B=b\nMB_TEST_C=file\n', encoding="utf-8")
    monkeypatch.setenv("MB_TEST_C", "from env")
    for name in ("MB_TEST_A", "MB_TEST_B"):
        monkeypatch.delenv(name, raising=False)
    load_dotenv(env_file)
    assert os.environ["MB_TEST_A"] == "from file"
    assert os.environ["MB_TEST_B"] == "b"
    assert os.environ["MB_TEST_C"] == "from env"
    for name in ("MB_TEST_A", "MB_TEST_B"):
        monkeypatch.delenv(name)

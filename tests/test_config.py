from pathlib import Path

import pytest

from troupe_bot.config import ConfigError, find_claude, load_config

GOOD = {
    "DISCORD_TOKEN": "abc.DEF-123_xyz",
    "CHANNEL_ID": "1562014364339408976",
    "CLAUDE_MODEL": "haiku",
    "DATA_DIR": "./data",
}


def load(env=None, root=Path("C:/proj"), which=lambda name: "C:/bin/claude.exe"):
    return load_config(env if env is not None else GOOD, root, which=which)


def test_valid_settings_are_parsed():
    cfg = load()
    assert cfg.discord_token == "abc.DEF-123_xyz"
    assert cfg.channel_id == 1562014364339408976
    assert cfg.claude_model == "haiku"
    assert cfg.claude_path == "C:/bin/claude.exe"


def test_relative_data_dir_is_resolved_against_the_project_root(tmp_path):
    cfg = load(root=tmp_path)
    assert cfg.data_dir == (tmp_path / "data").resolve()
    assert cfg.photos_dir == cfg.data_dir / "photos"
    assert cfg.xlsx_path == cfg.data_dir / "inventory.xlsx"


def test_absolute_data_dir_is_kept(tmp_path):
    cfg = load({**GOOD, "DATA_DIR": str(tmp_path / "elsewhere")})
    assert cfg.data_dir == (tmp_path / "elsewhere").resolve()


def test_missing_settings_are_all_named_in_one_error():
    with pytest.raises(ConfigError) as err:
        load({"CLAUDE_MODEL": "haiku"})
    message = str(err.value)
    assert "DISCORD_TOKEN" in message and "CHANNEL_ID" in message and "DATA_DIR" in message


def test_blank_values_count_as_missing():
    with pytest.raises(ConfigError):
        load({**GOOD, "DISCORD_TOKEN": "   "})


def test_channel_id_must_be_a_number():
    with pytest.raises(ConfigError, match="CHANNEL_ID"):
        load({**GOOD, "CHANNEL_ID": "資產登記"})


def test_placeholder_token_is_rejected_with_a_helpful_message():
    with pytest.raises(ConfigError, match="token"):
        load({**GOOD, "DISCORD_TOKEN": "你的bot_token"})


def test_error_messages_never_contain_the_token():
    secret = "SECRET.TOKEN.VALUE"
    with pytest.raises(ConfigError) as err:
        load({**GOOD, "DISCORD_TOKEN": secret, "CHANNEL_ID": "abc"})
    assert secret not in str(err.value)


def test_claude_must_be_found():
    with pytest.raises(ConfigError, match="claude"):
        find_claude(which=lambda name: None)


@pytest.mark.parametrize("path", ["C:/Users/x/AppData/Roaming/npm/claude.cmd", "C:/x/claude.BAT"])
def test_cmd_and_bat_shims_are_refused(path):
    with pytest.raises(ConfigError, match=r"\.exe"):
        find_claude(which=lambda name: path)


def test_exe_is_accepted():
    assert find_claude(which=lambda name: "C:/x/claude.exe") == "C:/x/claude.exe"

from troupe_bot import __main__ as entry
from troupe_bot.config import Config
from troupe_bot.store import ExcelBusy


def test_starting_while_excel_holds_the_file_open_explains_instead_of_crashing(tmp_path, monkeypatch, capsys):
    cfg = Config(discord_token="x", channel_id=1, claude_model="haiku", data_dir=tmp_path / "data", claude_path="claude.exe")
    monkeypatch.setattr(entry, "load_from_environment", lambda: cfg)
    monkeypatch.setattr(entry, "setup_logging", lambda cfg: None)

    def busy(self):
        raise ExcelBusy(str(self.path))

    monkeypatch.setattr(entry.Store, "ensure", busy)
    assert entry.main() == 5
    err = capsys.readouterr().err
    assert "Excel" in err and "關" in err

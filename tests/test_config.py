import pytest

from dali_iot import config


def test_arg_wins(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.toml")
    assert config.resolve_url("http://a/") == ("http://a", "arg")


def test_config_file(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.toml")
    config.save_url("http://gw")
    assert config.resolve_url(None) == ("http://gw", "config")


def test_missing_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "missing.toml")
    with pytest.raises(config.NoGatewayError):
        config.resolve_url(None)

"""Configuration loading, and the guarantee that credentials stay out of logs."""

from __future__ import annotations

import pytest

from slicedeck.config import DECKS, load_config
from slicedeck.sources import build_source

PASSWORD = "s3cret-do-not-log"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in list(dict(__import__("os").environ)):
        if key.startswith(("SLICEDECK_", "REOLINK_", "MJPEG_", "IMAGE_", "VIDEO_")):
            monkeypatch.delenv(key, raising=False)


def test_defaults_need_no_environment():
    config = load_config(env_file=None)
    assert config.source == "synthetic"
    assert config.deck is DECKS["xl"]
    assert config.interval == pytest.approx(0.5)


def test_environment_overrides_defaults(monkeypatch):
    monkeypatch.setenv("SLICEDECK_DECK", "mini")
    monkeypatch.setenv("SLICEDECK_FPS", "4")
    monkeypatch.setenv("SLICEDECK_FILTERS", "thermal, edges:2")
    monkeypatch.setenv("SLICEDECK_MOTION", "false")
    config = load_config(env_file=None)

    assert config.deck is DECKS["mini"]
    assert config.fps == 4
    assert config.filters == ("thermal", "edges:2")
    assert config.motion is False


def test_grid_overrides_produce_a_custom_deck(monkeypatch):
    monkeypatch.setenv("SLICEDECK_GRID_COLS", "6")
    monkeypatch.setenv("SLICEDECK_GRID_ROWS", "5")
    config = load_config(env_file=None)
    assert (config.deck.cols, config.deck.rows) == (6, 5)
    assert config.deck.keys == 30


def test_malformed_numbers_fall_back_instead_of_crashing(monkeypatch):
    monkeypatch.setenv("SLICEDECK_FPS", "fast")
    assert load_config(env_file=None).fps == 2.0


def test_dotenv_file_is_read_but_never_beats_the_real_environment(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("SLICEDECK_FPS=9\nSLICEDECK_DECK=mini\n", encoding="utf-8")
    monkeypatch.setenv("SLICEDECK_DECK", "plus")

    config = load_config(env_file=env_file)
    assert config.fps == 9  # taken from the file
    assert config.deck is DECKS["plus"]  # real environment wins


def test_reolink_url_is_built_from_the_environment(monkeypatch):
    monkeypatch.setenv("REOLINK_HOST", "10.0.0.5")
    monkeypatch.setenv("REOLINK_USER", "admin")
    monkeypatch.setenv("REOLINK_PASSWORD", PASSWORD)
    url = load_config(env_file=None).reolink_snapshot_url()
    assert url.startswith("http://10.0.0.5/cgi-bin/api.cgi")
    assert "cmd=Snap" in url


def test_missing_credentials_fail_loudly():
    config = load_config(env_file=None)
    with pytest.raises(ValueError, match="REOLINK_HOST"):
        config.reolink_snapshot_url()


def test_redacted_config_never_contains_the_password(monkeypatch):
    monkeypatch.setenv("REOLINK_HOST", "10.0.0.5")
    monkeypatch.setenv("REOLINK_PASSWORD", PASSWORD)
    config = load_config(env_file=None)
    assert PASSWORD not in repr(config.redacted())
    assert "password" not in repr(config.redacted()).lower()


def test_source_errors_do_not_leak_the_credentialled_url(monkeypatch):
    monkeypatch.setenv("SLICEDECK_SOURCE", "reolink")
    monkeypatch.setenv("REOLINK_HOST", "203.0.113.1")  # unroutable test range
    monkeypatch.setenv("REOLINK_PASSWORD", PASSWORD)
    from slicedeck.sources.base import SourceError

    source = build_source(load_config(env_file=None))
    try:
        with pytest.raises(SourceError) as caught:
            source.read()
        assert PASSWORD not in str(caught.value)
    finally:
        source.close()


def test_unknown_source_is_rejected(monkeypatch):
    monkeypatch.setenv("SLICEDECK_SOURCE", "carrier-pigeon")
    with pytest.raises(ValueError, match="carrier-pigeon"):
        build_source(load_config(env_file=None))

"""Tests for tests/fakes.py — FakeConfig.get_json() error tolerance."""

import json

import pytest

from tests.fakes import FakeConfig


class TestFakeConfigGetJson:
    """Verify FakeConfig.get_json() handles invalid JSON gracefully."""

    def test_invalid_json_returns_default_dict(self):
        cfg = FakeConfig({"k": "not-valid-json"})
        assert cfg.get_json("k") == {}

    def test_invalid_json_returns_custom_default(self):
        cfg = FakeConfig({"k": "not-valid-json"})
        assert cfg.get_json("k", default=[]) == []

    def test_valid_json_parsed_correctly(self):
        cfg = FakeConfig({"k": '{"a": 1}'})
        assert cfg.get_json("k") == {"a": 1}

    def test_empty_value_returns_default_dict(self):
        cfg = FakeConfig({"k": ""})
        assert cfg.get_json("k") == {}

    def test_empty_value_returns_custom_default(self):
        cfg = FakeConfig({"k": ""})
        assert cfg.get_json("k", default=[]) == []

    def test_missing_key_returns_default_dict(self):
        cfg = FakeConfig({})
        assert cfg.get_json("nonexistent") == {}

    def test_missing_key_returns_custom_default(self):
        cfg = FakeConfig({})
        assert cfg.get_json("nonexistent", default=[]) == []

    def test_set_json_round_trip(self):
        cfg = FakeConfig()
        cfg.set_json("k", {"x": [1, 2]})
        assert cfg.get_json("k") == {"x": [1, 2]}

    def test_non_string_value_returns_default(self):
        """FakeConfig.values may contain non-string types directly."""
        cfg = FakeConfig({"k": 123})
        assert cfg.get_json("k") == {}

"""Tests for re-read tracking in action ledger."""
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from brick_action_ledger import log_action, get_read_count


class TestReadCount:
    @pytest.fixture(autouse=True)
    def _tmp_ledger(self, tmp_path):
        self.ledger = tmp_path / "test-ledger.jsonl"
        self._patcher = patch("brick_action_ledger.LEDGER_PATH", self.ledger)
        self._patcher.start()
        yield
        self._patcher.stop()

    def test_first_read_returns_one(self):
        log_action("sess1", "Read", file_path="/src/app.py")
        assert get_read_count("sess1", "/src/app.py") == 1

    def test_second_read_returns_two(self):
        log_action("sess1", "Read", file_path="/src/app.py")
        log_action("sess1", "Read", file_path="/src/app.py")
        assert get_read_count("sess1", "/src/app.py") == 2

    def test_different_files_tracked_separately(self):
        log_action("sess1", "Read", file_path="/src/app.py")
        log_action("sess1", "Read", file_path="/src/utils.py")
        assert get_read_count("sess1", "/src/app.py") == 1
        assert get_read_count("sess1", "/src/utils.py") == 1

    def test_different_sessions_tracked_separately(self):
        log_action("sess1", "Read", file_path="/src/app.py")
        log_action("sess2", "Read", file_path="/src/app.py")
        assert get_read_count("sess1", "/src/app.py") == 1
        assert get_read_count("sess2", "/src/app.py") == 1

    def test_non_read_tools_not_counted(self):
        log_action("sess1", "Write", file_path="/src/app.py")
        assert get_read_count("sess1", "/src/app.py") == 0

    def test_read_count_in_logged_entry(self):
        log_action("sess1", "Read", file_path="/src/app.py")
        log_action("sess1", "Read", file_path="/src/app.py")
        lines = self.ledger.read_text().strip().split("\n")
        last = json.loads(lines[-1])
        assert last["read_count"] == 2

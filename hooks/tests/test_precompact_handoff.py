# hooks/tests/test_precompact_handoff.py
"""Tests for agent-authored handoff note storage."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestHandoffNote:
    def test_write_then_read_roundtrip(self, tmp_path):
        from precompact_handoff import write_note, read_note
        root = str(tmp_path)
        write_note("sess-1", "Refactoring parser; next: wire tests.", base_dir=root)
        assert read_note("sess-1", base_dir=root) == "Refactoring parser; next: wire tests."

    def test_read_absent_returns_none(self, tmp_path):
        from precompact_handoff import read_note
        assert read_note("missing", base_dir=str(tmp_path)) is None

    def test_write_overwrites(self, tmp_path):
        from precompact_handoff import write_note, read_note
        root = str(tmp_path)
        write_note("s", "first", base_dir=root)
        write_note("s", "second", base_dir=root)
        assert read_note("s", base_dir=root) == "second"

    def test_blank_note_is_rejected(self, tmp_path):
        from precompact_handoff import write_note, read_note
        root = str(tmp_path)
        write_note("s", "   ", base_dir=root)
        assert read_note("s", base_dir=root) is None

    def test_note_is_length_capped(self, tmp_path):
        from precompact_handoff import write_note, read_note, MAX_NOTE_CHARS
        root = str(tmp_path)
        write_note("s", "x" * (MAX_NOTE_CHARS + 500), base_dir=root)
        assert len(read_note("s", base_dir=root)) == MAX_NOTE_CHARS

    def test_session_id_is_sanitized_for_path(self, tmp_path):
        from precompact_handoff import write_note, read_note
        root = str(tmp_path)
        write_note("../evil", "data", base_dir=root)
        # Must stay inside base_dir — no traversal.
        for dirpath, _, files in os.walk(root):
            for fn in files:
                assert os.path.realpath(os.path.join(dirpath, fn)).startswith(
                    os.path.realpath(root))
        assert read_note("../evil", base_dir=root) == "data"

"""Tests for enrichment_id injection in Read and Write hooks."""
import importlib.util
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Import Read hook
_mod_path = os.path.join(os.path.dirname(__file__), "..", "enrich-pretool-read.py")
_spec = importlib.util.spec_from_file_location("enrich_pretool_read", _mod_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

# Import Write hook
_write_mod_path = os.path.join(os.path.dirname(__file__), "..", "enrich-posttool-write.py")
_write_spec = importlib.util.spec_from_file_location("enrich_posttool_write", _write_mod_path)
_write_mod = importlib.util.module_from_spec(_write_spec)
_write_spec.loader.exec_module(_write_mod)


class TestEnrichmentIdInReadContext:
    def test_enrichment_id_in_context_string(self):
        context = _mod.build_enrichment_context(
            file_path="/path/file.py",
            line_count=500,
            summary="File has 3 classes...",
            enrichment_id="test-eid-123",
        )
        assert "enrichment_id=test-eid-123" in context
        assert "\U0001f9f1 Brick enriched Read" in context

    def test_build_enrichment_context_contains_all_fields(self):
        context = _mod.build_enrichment_context(
            file_path="/src/app.py",
            line_count=350,
            summary="3 classes, 5 functions",
            enrichment_id="abc123",
        )
        assert "/src/app.py" in context
        assert "350" in context
        assert "enrichment_id=abc123" in context
        assert "3 classes, 5 functions" in context


class TestEnrichmentIdInWriteContext:
    def test_build_write_enrichment_context(self):
        context = _write_mod.build_write_enrichment_context(
            file_path="/src/app.py",
            summary="Missing error handling in try block",
            enrichment_id="def456",
        )
        assert "enrichment_id=def456" in context
        assert "\U0001f9f1 Brick reviewed Write" in context
        assert "/src/app.py" in context
        assert "Missing error handling" in context

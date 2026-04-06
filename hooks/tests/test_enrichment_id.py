"""Tests for enrichment_id injection in Read and Write hooks."""
import importlib.util
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from brick_common import build_enrichment_context


class TestEnrichmentIdInReadContext:
    def test_enrichment_id_in_context_string(self):
        context = build_enrichment_context(
            "Read",
            file_path="/path/file.py",
            summary="File has 3 classes...",
            enrichment_id="test-eid-123",
            extra_info="500 lines",
        )
        assert "enrichment_id=test-eid-123" in context
        assert "\U0001f9f1 Brick enriched Read" in context

    def test_build_enrichment_context_contains_all_fields(self):
        context = build_enrichment_context(
            "Read",
            file_path="/src/app.py",
            summary="3 classes, 5 functions",
            enrichment_id="abc123",
            extra_info="350 lines",
        )
        assert "/src/app.py" in context
        assert "350 lines" in context
        assert "enrichment_id=abc123" in context
        assert "3 classes, 5 functions" in context


class TestEnrichmentIdInWriteContext:
    def test_build_write_enrichment_context(self):
        context = build_enrichment_context(
            "Write",
            file_path="/src/app.py",
            summary="Missing error handling in try block",
            enrichment_id="def456",
            verb="reviewed",
        )
        assert "enrichment_id=def456" in context
        assert "\U0001f9f1 Brick reviewed Write" in context
        assert "/src/app.py" in context
        assert "Missing error handling" in context

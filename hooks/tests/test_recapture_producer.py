# hooks/tests/test_recapture_producer.py
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import precompact_config as cfg


import textwrap


def _write(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(textwrap.dedent(body))
    return p


class TestRecaptureConfig:
    def test_enabled_default_off(self, monkeypatch):
        monkeypatch.delenv("PRECOMPACT_RECAPTURE_ENABLED", raising=False)
        assert cfg.recapture_enabled() is False

    def test_enabled_on(self, monkeypatch):
        monkeypatch.setenv("PRECOMPACT_RECAPTURE_ENABLED", "1")
        assert cfg.recapture_enabled() is True

    def test_roots_default_home(self, monkeypatch):
        monkeypatch.delenv("PRECOMPACT_RECAPTURE_ROOTS", raising=False)
        assert cfg.recapture_roots() == [os.path.expanduser("~")]

    def test_roots_colon_split(self, monkeypatch):
        monkeypatch.setenv("PRECOMPACT_RECAPTURE_ROOTS", "/a:/b")
        assert cfg.recapture_roots() == ["/a", "/b"]

    def test_default_window_days(self, monkeypatch):
        monkeypatch.delenv("PRECOMPACT_RECAPTURE_DEFAULT_WINDOW_DAYS", raising=False)
        assert cfg.recapture_default_window_days() == 7


class TestFrontMatter:
    def test_true_boolean_accepted(self, tmp_path):
        import recapture_producer as rp
        p = _write(tmp_path, "ok.md", """\
            ---
            requires_recapture: true
            freshness_window_days: 7
            recapture_owner: "Q"
            recapture_trigger_files: "x/*"
            stale_action: "warn"
            ---
            body
        """)
        fm = rp.parse_front_matter(str(p))
        assert fm is not None
        assert fm["requires_recapture"] is True

    def test_false_excluded(self, tmp_path):
        import recapture_producer as rp
        p = _write(tmp_path, "false.md", """\
            ---
            requires_recapture: false
            ---
            requires_recapture: true   # decoy in body prose
        """)
        fm = rp.parse_front_matter(str(p))
        assert fm is not None
        assert fm["requires_recapture"] is False

    def test_no_front_matter_excluded(self, tmp_path):
        import recapture_producer as rp
        p = _write(tmp_path, "nofm.md", """\
            # just prose
            mentions requires_recapture: true in text
        """)
        assert rp.parse_front_matter(str(p)) is None


class TestStaleness:
    def _conformant(self, updated, window=7):
        return {
            "requires_recapture": True,
            "freshness_window_days": str(window),
            "recapture_owner": "Q",
            "recapture_trigger_files": "trig/*",
            "stale_action": "warn",
            "updated": updated,
        }

    def test_fresh_when_recent_and_no_trigger(self, tmp_path):
        import recapture_producer as rp
        fm = self._conformant("2026-06-22")
        verdict = rp.classify(str(tmp_path / "d.md"), fm,
                              now_epoch=rp._eod_epoch("2026-06-22"))
        assert verdict is None  # fresh, no breach

    def test_age_stale(self, tmp_path):
        import recapture_producer as rp
        fm = self._conformant("2026-06-01", window=7)
        verdict = rp.classify(str(tmp_path / "d.md"), fm,
                              now_epoch=rp._eod_epoch("2026-06-22"))
        assert verdict["reason"] == "age"
        assert verdict["stale_action"] == "warn"

    def test_trigger_mtime_stale(self, tmp_path):
        import recapture_producer as rp
        trig = tmp_path / "trig"
        trig.mkdir()
        f = trig / "src.py"
        f.write_text("x")
        # trigger edited strictly after updated end-of-day
        future = rp._eod_epoch("2026-06-22") + 86400
        os.utime(str(f), (future, future))
        fm = self._conformant("2026-06-22")
        fm["recapture_trigger_files"] = str(trig / "*")
        verdict = rp.classify(str(tmp_path / "d.md"), fm,
                              now_epoch=rp._eod_epoch("2026-06-22"))
        assert verdict["reason"] == "trigger_mtime"

    def test_trigger_missing_literal(self, tmp_path):
        import recapture_producer as rp
        fm = self._conformant("2026-06-22")
        fm["recapture_trigger_files"] = str(tmp_path / "gone.py")  # literal, absent
        verdict = rp.classify(str(tmp_path / "d.md"), fm,
                              now_epoch=rp._eod_epoch("2026-06-22"))
        assert verdict["reason"] == "trigger_missing"

    def test_same_day_trigger_not_stale(self, tmp_path):
        import recapture_producer as rp
        trig = tmp_path / "trig"
        trig.mkdir()
        f = trig / "src.py"
        f.write_text("x")
        same = rp._eod_epoch("2026-06-22") - 100  # within updated day
        os.utime(str(f), (same, same))
        fm = self._conformant("2026-06-22")
        fm["recapture_trigger_files"] = str(trig / "*")
        verdict = rp.classify(str(tmp_path / "d.md"), fm,
                              now_epoch=rp._eod_epoch("2026-06-22"))
        assert verdict is None

    # C1 RED tests — window=1 and window=0 must classify correctly
    def test_window_1_day_age_stale(self, tmp_path):
        """C1: freshness_window_days: 1 must be treated as integer 1, not bool True."""
        import recapture_producer as rp
        fm = self._conformant("2026-06-20", window=1)  # 2 days ago, window=1
        verdict = rp.classify(str(tmp_path / "d.md"), fm,
                              now_epoch=rp._eod_epoch("2026-06-22"))
        assert verdict is not None, (
            "window=1 should flag age-stale; got None (C1 regression: "
            "freshness_window_days coerced to bool True)")
        assert verdict["reason"] == "age"

    def test_window_0_no_age_rule(self, tmp_path):
        """C1: freshness_window_days: 0 means no age rule (window disabled)."""
        import recapture_producer as rp
        fm = self._conformant("2020-01-01", window=0)  # very old, but window=0
        verdict = rp.classify(str(tmp_path / "d.md"), fm,
                              now_epoch=rp._eod_epoch("2026-06-22"))
        # No age breach (window=0 disables it). No trigger breach (trig/* empty).
        assert verdict is None, (
            "window=0 should disable age rule; got verdict (C1 regression)")

    # C2 RED tests
    def test_updated_absent_falls_back_to_mtime(self, tmp_path):
        """C2a: absent 'updated' field falls back to os.path.getmtime."""
        import recapture_producer as rp
        p = tmp_path / "d.md"
        p.write_text("content")
        # Set file mtime to 30 days ago
        old_mtime = rp._eod_epoch("2026-05-20")
        os.utime(str(p), (old_mtime, old_mtime))
        fm = {
            "requires_recapture": True,
            "freshness_window_days": "7",
            "recapture_owner": "Q",
            "recapture_trigger_files": "",
            "stale_action": "warn",
            # no "updated" key
        }
        verdict = rp.classify(str(p), fm, now_epoch=rp._eod_epoch("2026-06-22"))
        assert verdict is not None, "absent updated should fall back to mtime (C2a)"
        assert verdict["reason"] == "age"

    def test_empty_glob_no_breach(self, tmp_path):
        """C2b: empty glob expansion (wildcard matching nothing) is NOT a breach."""
        import recapture_producer as rp
        fm = self._conformant("2026-06-22")
        # wildcard that will match nothing
        fm["recapture_trigger_files"] = str(tmp_path / "nonexistent_dir" / "*.py")
        verdict = rp.classify(str(tmp_path / "d.md"), fm,
                              now_epoch=rp._eod_epoch("2026-06-22"))
        assert verdict is None, (
            "empty glob expansion must not be a breach (C2b); got verdict")


class TestProduceRecapture:
    def test_none_when_no_docs(self, tmp_path, monkeypatch):
        """No recapture docs at all -> scan returns None (the empty-iter path)."""
        import recapture_producer as rp
        monkeypatch.setattr(rp, "_iter_recapture_docs", lambda roots: [])
        assert rp.scan([str(tmp_path)]) is None

    def test_none_when_all_fresh(self, tmp_path, monkeypatch):
        """A real conformant + fresh doc must be filtered out by scan (returns
        None) — exercises the freshness branch, not just the empty-iter path.
        Deterministic via injected now_epoch so it never rots."""
        import recapture_producer as rp
        doc = _write(tmp_path, "fresh.md", """\
            ---
            requires_recapture: true
            freshness_window_days: 7
            recapture_owner: "Q"
            recapture_trigger_files: "%s/nomatch/*"
            stale_action: "warn"
            updated: "2026-06-22"
            ---
            body
        """ % str(tmp_path))
        monkeypatch.setattr(rp, "_iter_recapture_docs", lambda roots: [str(doc)])
        # now == updated EOD, window 7d, trigger glob matches nothing -> fresh
        assert rp.scan([str(tmp_path)], now_epoch=rp._eod_epoch("2026-06-22")) is None

    def test_missing_fields_section(self, tmp_path, monkeypatch):
        import recapture_producer as rp
        p = tmp_path / "bad.md"
        p.write_text("---\nrequires_recapture: true\n---\nbody\n")
        monkeypatch.setattr(rp, "_iter_recapture_docs", lambda roots: [str(p)])
        section = rp.scan([str(tmp_path)])
        assert section["missing_fields"][0]["path"] == str(p)
        assert "stale_action" in section["missing_fields"][0]["missing"]
        assert section["stale"] == []

    def test_stale_section(self, tmp_path, monkeypatch):
        import recapture_producer as rp
        p = tmp_path / "old.md"
        p.write_text(
            "---\nrequires_recapture: true\n"
            "freshness_window_days: 7\nrecapture_owner: \"Q\"\n"
            "recapture_trigger_files: \"none/*\"\nstale_action: \"warn\"\n"
            "updated: \"2026-01-01\"\n---\nbody\n")
        monkeypatch.setattr(rp, "_iter_recapture_docs", lambda roots: [str(p)])
        section = rp.scan([str(tmp_path)])
        assert section["stale"][0]["reason"] == "age"
        assert section["missing_fields"] == []

    def test_produce_recapture_returns_keyed_dict(self, tmp_path, monkeypatch):
        import recapture_producer as rp
        p = tmp_path / "bad.md"
        p.write_text("---\nrequires_recapture: true\n---\nbody\n")
        monkeypatch.setattr(rp, "_iter_recapture_docs", lambda roots: [str(p)])
        monkeypatch.setenv("PRECOMPACT_RECAPTURE_ENABLED", "1")
        monkeypatch.setenv("PRECOMPACT_RECAPTURE_ROOTS", str(tmp_path))
        from precompact_producers import produce_recapture
        out = produce_recapture({"session_id": "s"})
        assert "stale_recapture" in out

    def test_produce_recapture_disabled_returns_none(self, monkeypatch):
        monkeypatch.setenv("PRECOMPACT_RECAPTURE_ENABLED", "0")
        from precompact_producers import produce_recapture
        assert produce_recapture({"session_id": "s"}) is None


class TestRegistration:
    def test_in_producers_dict(self):
        from precompact_producers import PRODUCERS, produce_recapture
        assert PRODUCERS["recapture"] is produce_recapture

    def test_in_producer_order_last(self):
        from precompact_orchestrator_lib import PRODUCER_ORDER
        assert PRODUCER_ORDER[-1] == "recapture"
        assert PRODUCER_ORDER[:5] == ["preserve", "git", "failures",
                                      "stats", "handoff"]


class TestCapsuleSurvival:
    def test_section_survives_merge(self):
        from precompact_capsule import merge_capsule
        results = {"recapture": {"stale_recapture": {
            "stale": [{"path": "/x", "owner": "Q",
                       "reason": "age", "stale_action": "warn"}],
            "missing_fields": []}}}
        cap = merge_capsule(results, failed=[], elapsed_ms=1)
        assert "stale_recapture" in cap
        assert "recapture" in cap["_producers_ok"]


class TestRender:
    def test_render_shows_stale_and_missing(self):
        from precompact_capsule import render_systemmessage
        cap = {
            "schema_version": 1, "_empty": False,
            "stale_recapture": {
                "stale": [{"path": "/home/q/.claude/docs/host-map.md",
                           "owner": "Q", "reason": "trigger_mtime",
                           "stale_action": "warn"}],
                "missing_fields": [{"path": "/home/q/LAB/claude-guards/README.md",
                                    "missing": ["freshness_window_days"]}],
            },
        }
        msg = render_systemmessage(cap)
        assert "host-map.md" in msg
        assert "[warn]" in msg
        assert "claude-guards/README.md" in msg

    def test_c3_no_body_leak_full_chain(self, tmp_path, monkeypatch):
        """C3: feed a real fixture doc (multi-line action_boundary + body) through
        scan()->produce_recapture()->render_systemmessage(); assert no body
        substring leaks into rendered output."""
        import recapture_producer as rp
        from precompact_producers import produce_recapture
        from precompact_capsule import render_systemmessage, merge_capsule

        # A fixture doc with multi-line action_boundary and a distinctive body phrase
        BODY_SENTINEL = "SECRET_BODY_TEXT_MUST_NOT_APPEAR_IN_RENDER"
        ACTION_SENTINEL = "action_boundary_secret_phrase_must_not_appear"
        doc = tmp_path / "fixture.md"
        doc.write_text(
            "---\n"
            "requires_recapture: true\n"
            "freshness_window_days: 7\n"
            "recapture_owner: Q\n"
            "recapture_trigger_files: nonexistent_literal_path_gone.py\n"
            "stale_action: warn\n"
            "updated: 2026-01-01\n"
            f"action_boundary: {ACTION_SENTINEL} line1\n"
            f"  {ACTION_SENTINEL} line2\n"
            "---\n"
            f"# Body\n{BODY_SENTINEL}\n"
            "More body content here.\n"
        )
        monkeypatch.setattr(rp, "_iter_recapture_docs", lambda roots: [str(doc)])
        monkeypatch.setenv("PRECOMPACT_RECAPTURE_ENABLED", "1")
        monkeypatch.setenv("PRECOMPACT_RECAPTURE_ROOTS", str(tmp_path))

        out = produce_recapture({"session_id": "s"})
        assert out is not None, "produce_recapture must return a section for stale doc"

        cap = merge_capsule({"recapture": out}, failed=[], elapsed_ms=1)
        msg = render_systemmessage(cap)
        assert msg is not None

        # Body and action_boundary text must NOT appear in render
        assert BODY_SENTINEL not in msg, (
            f"C3: body text leaked into rendered output: {msg[:200]}")
        assert ACTION_SENTINEL not in msg, (
            f"C3: action_boundary text leaked into rendered output: {msg[:200]}")

        # Frontmatter structure must not leak either. Folds in the former
        # near-vacuous test_no_doc_body_leak (which only checked a hand-built
        # cap dict that never contained these tokens) — now proven through the
        # real scan->produce->render chain.
        for banned in ("action_boundary", "freshness_window_days:", "---"):
            assert banned not in msg, f"C3: frontmatter token leaked: {banned!r}"


class TestFailOpenAndParity:
    def test_recapture_in_default_order_runs_clean(self):
        """GoldenParity safety: recapture present in default order."""
        from precompact_orchestrator_lib import PRODUCER_ORDER
        assert "recapture" in PRODUCER_ORDER

    def test_c4_produce_recapture_never_raises_on_malformed_doc(self, tmp_path, monkeypatch):
        """C4: produce_recapture must return a value and NOT raise on a malformed doc.
        The never-raise guarantee is tested at the producer, not delegated to _main."""
        import recapture_producer as rp

        # Force parse_front_matter to raise OSError on every path
        def _boom(p):
            raise OSError("injected fault")

        monkeypatch.setattr(rp, "parse_front_matter", _boom)

        bad = tmp_path / "x.md"
        bad.write_text("---\nrequires_recapture: true\n---\n")
        monkeypatch.setattr(rp, "_iter_recapture_docs", lambda roots: [str(bad)])
        monkeypatch.setenv("PRECOMPACT_RECAPTURE_ENABLED", "1")
        monkeypatch.setenv("PRECOMPACT_RECAPTURE_ROOTS", str(tmp_path))

        from precompact_producers import produce_recapture
        # Must not raise — must return a value (None or a dict)
        raised = False
        result = None
        try:
            result = produce_recapture({"session_id": "s"})
        except Exception as e:
            raised = True
            result = f"RAISED: {e}"

        assert not raised, (
            f"C4: produce_recapture raised on malformed doc: {result}")
        # When every doc raises, scan returns None -> produce returns None
        assert result is None, (
            f"C4: expected None when all docs error, got: {result}")

    def test_r2d_scan_failure_logs_diagnostic_not_silent(self, tmp_path, monkeypatch):
        """R2d: a top-level scan() failure must stay fail-open (None, per C4) AND
        write an actionable fault record — not be swallowed silently."""
        import json
        import hook_utils
        import recapture_producer as rp

        ledger = tmp_path / "faults.jsonl"
        monkeypatch.setattr(hook_utils, "_LEDGER_PATH", str(ledger))

        def _boom(roots, **kw):
            raise RuntimeError("injected scan failure")

        monkeypatch.setattr(rp, "scan", _boom)
        monkeypatch.setenv("PRECOMPACT_RECAPTURE_ENABLED", "1")
        monkeypatch.setenv("PRECOMPACT_RECAPTURE_ROOTS", str(tmp_path))

        from precompact_producers import produce_recapture
        result = produce_recapture({"session_id": "s"})

        # C4 fail-open preserved
        assert result is None, f"expected None on scan failure, got {result!r}"
        # R2d: the failure must be recorded, not silently swallowed
        assert ledger.exists(), "R2d: scan failure must write a fault record"
        records = [json.loads(ln) for ln in ledger.read_text().splitlines() if ln.strip()]
        assert any(r.get("reason_class") == "recapture_scan_failed" for r in records), (
            f"R2d: expected a recapture_scan_failed diagnostic, got {records}")

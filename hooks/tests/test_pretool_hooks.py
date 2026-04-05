"""Tests for enrich-pretool-commit and enrich-pretool-pr hooks."""
import importlib.util
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# -- Import hyphenated modules via importlib ----------------------------------

sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_commit_path = os.path.join(os.path.dirname(__file__), "..", "enrich-pretool-commit.py")
_commit_spec = importlib.util.spec_from_file_location("enrich_pretool_commit", _commit_path)
_commit_mod = importlib.util.module_from_spec(_commit_spec)
_commit_spec.loader.exec_module(_commit_mod)

_pr_path = os.path.join(os.path.dirname(__file__), "..", "enrich-pretool-pr.py")
_pr_spec = importlib.util.spec_from_file_location("enrich_pretool_pr", _pr_path)
_pr_mod = importlib.util.module_from_spec(_pr_spec)
_pr_spec.loader.exec_module(_pr_mod)


# =============================================================================
# Commit hook tests
# =============================================================================

class TestCommitRegex:
    def test_matches_git_commit_m(self):
        assert _commit_mod._COMMIT_RE.search('git commit -m "msg"')

    def test_matches_git_commit_bare(self):
        assert _commit_mod._COMMIT_RE.search("git commit")

    def test_matches_git_commit_amend(self):
        assert _commit_mod._COMMIT_RE.search("git commit --amend")

    def test_no_match_git_log(self):
        assert _commit_mod._COMMIT_RE.search("git log") is None

    def test_no_match_git_push(self):
        assert _commit_mod._COMMIT_RE.search("git push") is None


class TestAllowEmptyRegex:
    def test_matches_allow_empty(self):
        assert _commit_mod._ALLOW_EMPTY_RE.search("git commit --allow-empty -m 'x'")

    def test_no_match_normal_commit(self):
        assert _commit_mod._ALLOW_EMPTY_RE.search("git commit -m 'x'") is None


class TestGetStagedDiff:
    @patch("subprocess.run")
    def test_returns_none_when_no_staged(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        diff, stats = _commit_mod._get_staged_diff()
        assert diff is None
        assert stats is None

    @patch("subprocess.run")
    def test_returns_none_on_stats_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        diff, stats = _commit_mod._get_staged_diff()
        assert diff is None
        assert stats is None

    @patch("subprocess.run")
    def test_returns_diff_and_stats(self, mock_run):
        def side_effect(cmd, **kwargs):
            if "--stat" in cmd:
                return MagicMock(returncode=0, stdout=" file.py | 3 +++")
            return MagicMock(returncode=0, stdout="+hello\n-world")

        mock_run.side_effect = side_effect
        diff, stats = _commit_mod._get_staged_diff()
        assert diff == "+hello\n-world"
        assert stats == "file.py | 3 +++"

    @patch("subprocess.run")
    def test_truncates_large_diff(self, mock_run):
        large_diff = "x" * 50000

        def side_effect(cmd, **kwargs):
            if "--stat" in cmd:
                return MagicMock(returncode=0, stdout="file.py | 999 +++")
            return MagicMock(returncode=0, stdout=large_diff)

        mock_run.side_effect = side_effect
        diff, stats = _commit_mod._get_staged_diff()
        assert len(diff) < len(large_diff)
        assert "[... truncated ...]" in diff


class TestCallBrick:
    @patch("urllib.request.urlopen")
    def test_returns_summary_on_success(self, mock_urlopen):
        response_data = {
            "tree": {"root": {"content": "feat: add new feature"}}
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = _commit_mod._call_brick("some diff", "test-key")
        assert result == "feat: add new feature"

    @patch("urllib.request.urlopen")
    def test_returns_none_on_timeout(self, mock_urlopen):
        import socket
        mock_urlopen.side_effect = socket.timeout("timed out")
        result = _commit_mod._call_brick("some diff", "test-key")
        assert result is None

    @patch("urllib.request.urlopen")
    def test_returns_none_on_empty_content(self, mock_urlopen):
        response_data = {"tree": {"root": {"content": ""}}}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = _commit_mod._call_brick("diff", "key")
        assert result is None


# =============================================================================
# PR hook tests
# =============================================================================

class TestPRCreateRegex:
    def test_matches_gh_pr_create(self):
        assert _pr_mod._PR_CREATE_RE.search('gh pr create --title "x"')

    def test_matches_bare_gh_pr_create(self):
        assert _pr_mod._PR_CREATE_RE.search("gh pr create")

    def test_no_match_gh_issue_create(self):
        assert _pr_mod._PR_CREATE_RE.search("gh issue create") is None

    def test_no_match_gh_pr_list(self):
        assert _pr_mod._PR_CREATE_RE.search("gh pr list") is None


class TestDetectBaseBranch:
    @patch("subprocess.run")
    def test_returns_main_when_upstream_fails(self, mock_run):
        def side_effect(cmd, **kwargs):
            if "HEAD@{upstream}" in cmd:
                return MagicMock(returncode=1, stdout="")
            if "--verify" in cmd and "main" in cmd:
                return MagicMock(returncode=0, stdout="abc123")
            return MagicMock(returncode=1, stdout="")

        mock_run.side_effect = side_effect
        assert _pr_mod._detect_base_branch() == "main"

    @patch("subprocess.run")
    def test_returns_master_when_main_missing(self, mock_run):
        def side_effect(cmd, **kwargs):
            if "HEAD@{upstream}" in cmd:
                return MagicMock(returncode=1, stdout="")
            if "--verify" in cmd and "main" in cmd:
                return MagicMock(returncode=1, stdout="")
            if "--verify" in cmd and "master" in cmd:
                return MagicMock(returncode=0, stdout="abc123")
            return MagicMock(returncode=1, stdout="")

        mock_run.side_effect = side_effect
        assert _pr_mod._detect_base_branch() == "master"

    @patch("subprocess.run")
    def test_returns_upstream_branch(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="origin/develop\n")
        assert _pr_mod._detect_base_branch() == "develop"

    @patch("subprocess.run")
    def test_fallback_to_head(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        assert _pr_mod._detect_base_branch() == "HEAD~10"


class TestGetBranchDiff:
    @patch("subprocess.run")
    def test_returns_none_when_no_diff(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        diff, commits = _pr_mod._get_branch_diff("main")
        assert diff is None
        assert commits is None

    @patch("subprocess.run")
    def test_returns_diff_and_commits(self, mock_run):
        def side_effect(cmd, **kwargs):
            if "diff" in cmd:
                return MagicMock(returncode=0, stdout="+new line")
            if "log" in cmd:
                return MagicMock(returncode=0, stdout="abc123 feat: something")
            return MagicMock(returncode=1, stdout="")

        mock_run.side_effect = side_effect
        diff, commits = _pr_mod._get_branch_diff("main")
        assert diff == "+new line"
        assert commits == "abc123 feat: something"

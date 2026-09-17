import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import github_detail


def response(data, more=False):
    return {"status": "ok", "data": data, "has_next_page": more}


class DetailTests(unittest.TestCase):
    def test_pr_uses_issue_comments_and_timeline_and_current_head_checks(self):
        paths = []

        def get(path):
            paths.append(path)
            if path == "/repos/a/b/pulls/7":
                return response({"head": {"sha": "abc"}})
            if "/check-runs?" in path:
                return response({"check_runs": [{"name": "test"}]})
            return response([])

        with patch.object(github_detail, "GitHubReader") as reader:
            reader.return_value.get.side_effect = get
            report = github_detail.collect("a/b", 7, "pr")
        self.assertIn("/repos/a/b/issues/7/comments?per_page=100&page=1", paths)
        self.assertIn("/repos/a/b/issues/7/timeline?per_page=100&page=1", paths)
        self.assertIn("/repos/a/b/pulls/7/comments?per_page=100&page=1", paths)
        self.assertIn("/repos/a/b/commits/abc/check-runs?per_page=100&page=1", paths)
        self.assertEqual(report["status"], "complete")
        self.assertFalse(report["scope"]["search_requested"])

    def test_later_page_claim_is_collected(self):
        with patch.object(github_detail, "GitHubReader") as reader:
            reader.return_value.get.side_effect = [response({}), response([], True),
                                                   response([{"body": "I am working on this"}]), response([])]
            report = github_detail.collect("a/b", 1)
        self.assertEqual(report["sources"]["comments"]["data"][0]["body"], "I am working on this")
        self.assertEqual(report["status"], "complete")

    def test_page_limit_marks_report_partial(self):
        with patch.object(github_detail, "GitHubReader") as reader:
            reader.return_value.get.side_effect = [response({}), response([{"id": 1}], True), response([])]
            report = github_detail.collect("a/b", 1, pages=1)
        self.assertEqual(report["status"], "partial")
        self.assertTrue(report["sources"]["comments"]["truncated"])

    def test_failed_later_page_retains_evidence(self):
        with patch.object(github_detail, "GitHubReader") as reader:
            reader.return_value.get.side_effect = [response([{"id": 1}], True),
                                                   {"status": "unavailable", "reason": "local_request_or_time_budget_exhausted"}]
            result = github_detail.read_pages(reader.return_value, "/list?per_page=100", 3)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["data"], [{"id": 1}])
        self.assertEqual(result["pages"][-1]["reason"], "local_request_or_time_budget_exhausted")

    def test_incomplete_search_is_not_complete(self):
        with patch.object(github_detail, "GitHubReader") as reader:
            reader.return_value.get.side_effect = [response({}), response([]), response([]),
                response({"items": [{"number": 2}], "incomplete_results": True})]
            report = github_detail.collect("a/b", 1, search="error")
        self.assertEqual(report["status"], "partial")
        self.assertTrue(report["sources"]["search"]["incomplete_results"])

    def test_invalid_budget_never_starts_network(self):
        with patch.object(github_detail, "GitHubReader") as reader:
            with self.assertRaises(ValueError):
                github_detail.collect("a/b", 1, pages=0)
            reader.assert_not_called()

    def test_search_total_exceeds_returned_rows_without_next_link(self):
        with patch.object(github_detail, "GitHubReader") as reader:
            reader.return_value.get.return_value = response({"items": [{"number": 2}], "total_count": 1001})
            result = github_detail.read_pages(reader.return_value, "/search/issues?q=x&per_page=100", 3, "items")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["total_count"], 1001)

    def test_api_capped_commits_cannot_report_complete(self):
        with patch.object(github_detail, "GitHubReader") as reader:
            reader.return_value.get.side_effect = [response({"head": {"sha": "abc"}, "commits": 251}),
                response([]), response([]), response([]), response([]), response([{}] * 250),
                response({"check_runs": []})]
            report = github_detail.collect("a/b", 1, "pr")
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["sources"]["commits"]["total_count"], 251)


if __name__ == "__main__":
    unittest.main()

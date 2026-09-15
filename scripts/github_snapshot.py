#!/usr/bin/env python3
"""Bounded, read-only GitHub REST snapshot. Not a full contribution assessment."""

import argparse
import base64
import json
import os
import socket
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener

from workflow import now, parse_repo


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHubReader:
    def __init__(self, timeout=10, seconds=90, requests=18):
        self.timeout = timeout
        self.deadline = time.monotonic() + seconds
        self.requests_left = requests
        self.stopped = None
        self.opener = build_opener(NoRedirect())
        self.token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")

    def get(self, endpoint):
        url = "https://api.github.com" + endpoint
        result = {"url": url, "checked_at": now(), "status": "unavailable"}
        remaining = self.deadline - time.monotonic()
        if self.stopped or self.requests_left <= 0 or remaining <= 0:
            result["reason"] = self.stopped or "local_request_or_time_budget_exhausted"
            return result
        self.requests_left -= 1
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "open-source-contributor-skill",
                   "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        request = Request(url, headers=headers, method="GET")
        try:
            with self.opener.open(request, timeout=min(self.timeout, remaining)) as response:
                payload = response.read(2_000_001)
                result["http_status"] = response.status
                result["has_next_page"] = 'rel="next"' in response.headers.get("Link", "")
                result["rate_remaining"] = response.headers.get("X-RateLimit-Remaining")
                if len(payload) > 2_000_000:
                    result["reason"] = "response_size_limit"
                else:
                    result["data"] = json.loads(payload)
                    result["status"] = "ok"
        except HTTPError as exc:
            result["http_status"] = exc.code
            result["reason"] = "http_error"
            if exc.code in (401, 403, 429):
                self.stopped = "authentication_permission_or_rate_limit"
                result["reason"] = self.stopped
            elif exc.code in (301, 302, 307, 308):
                result["reason"] = "redirect_not_followed_verify_canonical_repository"
            elif exc.code == 404:
                result["reason"] = "not_found_or_not_visible_with_current_access"
            if exc.headers:
                result["retry_after"] = exc.headers.get("Retry-After")
                result["rate_reset"] = exc.headers.get("X-RateLimit-Reset")
        except (URLError, TimeoutError, socket.timeout, OSError):
            # Avoid echoing proxy addresses, credentials, or raw transport exceptions.
            self.stopped = "network_or_tls_error"
            result["reason"] = self.stopped
        except (ValueError, UnicodeError):
            result["reason"] = "invalid_json_response"
        return result


def select(data, keys):
    # Absence is not the same evidence as an explicit null (e.g. merged_at).
    return {key: data[key] for key in keys if key in data}


def compact_item(item):
    result = select(item, (
        "number", "title", "html_url", "state", "created_at", "updated_at", "closed_at",
        "merged_at", "merged", "merge_commit_sha", "draft", "author_association", "comments", "body",
    ))
    result["author"] = select(item.get("user") or {}, ("login", "type"))
    result["assignees"] = [user.get("login") for user in item.get("assignees", [])]
    result["labels"] = [label.get("name") for label in item.get("labels", [])]
    body = result.get("body") or ""
    result["body_truncated"] = len(body) > 12000
    result["body"] = body[:12000]
    result["merge_status"] = (
        "unknown" if "merged_at" not in item
        else "merged" if item["merged_at"]
        else "not_merged"
    )
    if "head" in item:
        result["head_sha"] = (item.get("head") or {}).get("sha")
        result["base_branch"] = (item.get("base") or {}).get("ref")
    return result


def collect(repo, reader, sample=5):
    repo = parse_repo(repo)
    base = "/repos/" + repo
    report = {
        "schema_version": 1, "repo": repo, "checked_at": now(), "status": "partial",
        "scope": {
            "sample_per_list": sample, "pagination": "first page only",
            "untrusted_source_data": True,
            "not_covered": ["complete comments/timelines", "duplicate search", "external forums",
                            "full organization policies", "local reproduction", "all PR reviews"],
        },
        "sources": {},
    }
    sources = report["sources"]
    metadata = reader.get(base)
    sources["repository"] = metadata
    if metadata["status"] != "ok":
        report["status"] = "unavailable"
        return report
    metadata["data"] = select(metadata["data"], (
        "full_name", "html_url", "description", "default_branch", "archived", "disabled",
        "fork", "private", "language", "pushed_at", "updated_at", "license", "has_issues",
        "parent", "source",
    ))
    # Resolve one branch commit, then pin document reads to it to avoid mixing revisions.
    branch = metadata["data"]["default_branch"]
    commit = reader.get(base + "/commits/" + quote(branch, safe=""))
    sources["head"] = commit
    ref = branch
    if commit["status"] == "ok":
        ref = commit["data"]["sha"]
        commit["data"] = select(commit["data"], ("sha", "html_url"))
    else:
        report["scope"]["unresolved_commit"] = True
    listings = []
    for folder in ("", ".github", "docs"):
        endpoint = base + "/contents" + ("/" + folder if folder else "") + "?ref=" + quote(ref, safe="")
        response = reader.get(endpoint)
        sources["directory:" + (folder or "root")] = response
        if response["status"] == "ok" and isinstance(response["data"], list):
            response["data"] = [select(item, ("name", "path", "type", "html_url")) for item in response["data"]]
            listings.extend(response["data"])
    def document_rank(item):
        name = item["name"].lower()
        if name.startswith("contributing"):
            return 0
        if name == "agents.md":
            return 1
        if name.startswith("readme"):
            return 2
        if any(word in name for word in ("development", "pull_request_template", "security", "ai-policy")):
            return 3
        return 99
    documents = sorted((item for item in listings if item["type"] == "file" and document_rank(item) < 99),
                       key=lambda item: (document_rank(item), item["path"]))[:5]
    for item in documents:
        response = reader.get(base + "/contents/" + quote(item["path"], safe="/") + "?ref=" + quote(ref, safe=""))
        sources["document:" + item["path"]] = response
        if response["status"] == "ok":
            raw = response["data"]
            if raw.get("encoding") == "base64":
                try:
                    body = base64.b64decode(raw.get("content", "")).decode("utf-8", errors="replace")
                    response["data"] = {"path": item["path"], "html_url": raw.get("html_url"), "ref": ref,
                                        "text": body[:24000], "truncated": len(body) > 24000}
                except ValueError:
                    response["status"] = "unavailable"
                    response["reason"] = "invalid_document_encoding"
                    response.pop("data", None)
            else:
                response["status"] = "unavailable"
                response["reason"] = "document_content_not_returned"
                response.pop("data", None)
    for name, endpoint in (
        ("open_issues", base + f"/issues?state=open&sort=updated&direction=desc&per_page={sample}"),
        ("open_prs", base + f"/pulls?state=open&sort=updated&direction=desc&per_page={sample}"),
        ("closed_prs", base + f"/pulls?state=closed&sort=updated&direction=desc&per_page={sample}"),
    ):
        response = reader.get(endpoint)
        sources[name] = response
        if response["status"] == "ok":
            items = response["data"]
            if name == "open_issues":
                response["pr_rows_excluded"] = sum("pull_request" in item for item in items)
                items = [item for item in items if "pull_request" not in item]
            response["data"] = [compact_item(item) for item in items]
    closed = sources.get("closed_prs", {})
    if closed.get("status") == "ok":
        for item in closed["data"][:2]:
            detail = reader.get(base + "/pulls/" + str(item["number"]))
            sources[f"pr_detail:{item['number']}"] = detail
            if detail["status"] == "ok":
                detail["data"] = compact_item(detail["data"])
    report["status"] = "sample_collected" if all(value["status"] == "ok" for value in sources.values()) else "partial"
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo")
    parser.add_argument("--sample", type=int, default=5, help="1-10 rows per list (not exhaustive)")
    parser.add_argument("--timeout", type=float, default=8, help="Per-request timeout in seconds")
    parser.add_argument("--seconds", type=float, default=60, help="Soft overall budget; a streaming read can exceed it")
    parser.add_argument("--requests", type=int, default=18, help="Maximum GET requests")
    parser.add_argument("--output", type=Path, help="New JSON evidence file outside the upstream checkout")
    args = parser.parse_args(argv)
    try:
        repo = parse_repo(args.repo)
        if not 1 <= args.sample <= 10 or not 0 < args.timeout <= 30 or not 0 < args.seconds <= 120 or not 1 <= args.requests <= 30:
            raise ValueError("Use sample 1-10, timeout (0,30], seconds (0,120], requests 1-30.")
        if args.output and args.output.exists():
            raise ValueError("Output already exists; use a new dated filename to preserve evidence.")
        report = collect(repo, GitHubReader(args.timeout, args.seconds, args.requests), args.sample)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(report, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            print(json.dumps({"status": report["status"], "output": str(args.output.resolve())}))
        else:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2 if report["status"] == "unavailable" else 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

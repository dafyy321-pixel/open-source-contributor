#!/usr/bin/env python3
"""Bounded read-only details for one GitHub Issue or Pull Request."""
import argparse, json, sys
from pathlib import Path
from urllib.parse import quote
from github_snapshot import GitHubReader
from workflow import parse_repo, now

def read_pages(reader, endpoint, limit, items_key=None):
    pages, items = [], []
    for page in range(1, limit + 1):
        response = reader.get(f"{endpoint}&page={page}")
        pages.append(response)
        if response.get("status") != "ok":
            break
        data = response.get("data")
        batch = data.get(items_key) if items_key and isinstance(data, dict) else data
        if not isinstance(batch, list):
            response["status"] = "unavailable"
            response["reason"] = "unexpected_list_payload"
            break
        items.extend(batch)
        if not response.get("has_next_page"):
            break
    incomplete = any(isinstance(p.get("data"), dict) and p["data"].get("incomplete_results") for p in pages)
    totals = [p["data"]["total_count"] for p in pages
              if isinstance(p.get("data"), dict) and isinstance(p["data"].get("total_count"), int)]
    total = max(totals) if totals else None
    complete = (all(p.get("status") == "ok" for p in pages)
                and not pages[-1].get("has_next_page") and not incomplete
                and (total is None or len(items) >= total))
    # Keep page metadata and failures, but store collected rows only once.
    return {"status": "ok" if complete else "partial", "data": items,
            "pages": [{k: v for k, v in p.items() if k != "data"} for p in pages],
            "truncated": not complete, "incomplete_results": incomplete, "total_count": total}


def collect(repo, number, kind="issue", timeout=8, seconds=45, search=None, pages=3, requests=30):
    if kind not in ("issue", "pr") or number < 1 or not 1 <= pages <= 10 or not 1 <= requests <= 100 or timeout <= 0 or seconds <= 0:
        raise ValueError("Invalid kind, number, pagination or request/time budget")
    repo = parse_repo(repo); reader = GitHubReader(timeout, seconds, requests=requests)
    base = f"/repos/{repo}/{ 'issues' if kind == 'issue' else 'pulls'}/{number}"
    issue_base = f"/repos/{repo}/issues/{number}"
    result = {"schema_version": 1, "repo": repo, "number": number, "kind": kind, "checked_at": now(), "status": "partial", "sources": {}}
    result["scope"] = {"max_pages_per_list": pages, "request_budget": requests,
                       "not_covered": ["unqueried keywords", "linked item details", "target branch fix verification", "release verification", "private work"],
                       "search_requested": bool(search)}
    result["sources"]["detail"] = reader.get(base)
    result["sources"]["comments"] = read_pages(reader, issue_base + "/comments?per_page=100", pages)
    result["sources"]["timeline"] = read_pages(reader, issue_base + "/timeline?per_page=100", pages)
    if kind == "pr":
        result["sources"]["reviews"] = read_pages(reader, base + "/reviews?per_page=100", pages)
        result["sources"]["review_comments"] = read_pages(reader, base + "/comments?per_page=100", pages)
        result["sources"]["commits"] = read_pages(reader, base + "/commits?per_page=100", pages)
        expected = (result["sources"]["detail"].get("data") or {}).get("commits")
        commits = result["sources"]["commits"]
        if isinstance(expected, int) and len(commits["data"]) < expected:
            commits.update(status="partial", truncated=True, total_count=expected)
        sha = (result["sources"]["detail"].get("data") or {}).get("head", {}).get("sha")
        result["sources"]["checks"] = read_pages(reader, f"/repos/{repo}/commits/{sha}/check-runs?per_page=100", pages, "check_runs") if sha else {"status": "unavailable", "reason": "head_sha_unavailable"}
    if search:
        q = quote(f"repo:{repo} {search}")
        result["sources"]["search"] = read_pages(reader, f"/search/issues?q={q}&per_page=100", pages, "items")
    result["status"] = "complete" if all(v.get("status") == "ok" for v in result["sources"].values()) else "partial"
    return result

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("repo"); p.add_argument("number", type=int); p.add_argument("--kind", choices=("issue","pr"), default="issue"); p.add_argument("--search", help="optional repository keyword search"); p.add_argument("--output", type=Path)
    p.add_argument("--pages", type=int, default=3)
    p.add_argument("--requests", type=int, default=30)
    p.add_argument("--seconds", type=float, default=45)
    a=p.parse_args(argv)
    try:
        report=collect(a.repo,a.number,a.kind,search=a.search,pages=a.pages,requests=a.requests,seconds=a.seconds)
        if a.output:
            if a.output.exists(): raise ValueError("Output already exists; use a new evidence filename")
            a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
            print(json.dumps({"status":report["status"],"output":str(a.output.resolve())},ensure_ascii=False))
        else: print(json.dumps(report,ensure_ascii=False,indent=2))
        return 0
    except (OSError,ValueError,TypeError) as e: print(f"Error: {e}",file=sys.stderr); return 2
if __name__ == "__main__": sys.exit(main())

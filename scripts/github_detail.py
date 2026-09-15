#!/usr/bin/env python3
"""Bounded read-only details for one GitHub Issue or Pull Request."""
import argparse, json, re, sys
from pathlib import Path
from urllib.parse import quote
from github_snapshot import GitHubReader
from workflow import parse_repo, now

def collect(repo, number, kind="issue", timeout=8, seconds=45, search=None):
    repo = parse_repo(repo); reader = GitHubReader(timeout, seconds, requests=8)
    base = f"/repos/{repo}/{ 'issues' if kind == 'issue' else 'pulls'}/{number}"
    result = {"schema_version": 1, "repo": repo, "number": number, "kind": kind, "checked_at": now(), "status": "partial", "sources": {}}
    result["sources"]["detail"] = reader.get(base)
    result["sources"]["comments"] = reader.get(base + "/comments?per_page=100")
    result["sources"]["timeline"] = reader.get(base + "/timeline?per_page=100")
    if kind == "pr":
        result["sources"]["reviews"] = reader.get(base + "/reviews?per_page=100")
        result["sources"]["review_comments"] = reader.get(f"/repos/{repo}/pulls/{number}/comments?per_page=100")
        result["sources"]["commits"] = reader.get(f"/repos/{repo}/pulls/{number}/commits?per_page=100")
        sha = (result["sources"]["detail"].get("data") or {}).get("head", {}).get("sha")
        result["sources"]["checks"] = reader.get(f"/repos/{repo}/commits/{sha}/check-runs") if sha else {"status": "unavailable", "reason": "head_sha_unavailable"}
    if search:
        q = quote(f"repo:{repo} {search}")
        result["sources"]["search"] = reader.get(f"/search/issues?q={q}&per_page=20")
    result["status"] = "complete" if all(v.get("status") == "ok" for v in result["sources"].values()) else "partial"
    return result

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("repo"); p.add_argument("number", type=int); p.add_argument("--kind", choices=("issue","pr"), default="issue"); p.add_argument("--search", help="optional repository keyword search"); p.add_argument("--output", type=Path)
    a=p.parse_args(argv)
    try:
        report=collect(a.repo,a.number,a.kind,search=a.search)
        if a.output:
            if a.output.exists(): raise ValueError("Output already exists; use a new evidence filename")
            a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
            print(json.dumps({"status":report["status"],"output":str(a.output.resolve())},ensure_ascii=False))
        else: print(json.dumps(report,ensure_ascii=False,indent=2))
        return 0
    except (OSError,ValueError,TypeError) as e: print(f"Error: {e}",file=sys.stderr); return 2
if __name__ == "__main__": sys.exit(main())

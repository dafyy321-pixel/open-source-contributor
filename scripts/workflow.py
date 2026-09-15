#!/usr/bin/env python3
"""Local contribution records. Python 3.10+, standard library only; no network."""

import argparse
import json
import os
import re
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


PHASES = (
    "assessing", "awaiting_selection", "investigating", "awaiting_maintainer",
    "implementing", "ready_for_pr", "reviewing", "merged", "closed", "paused",
)
ALLOWED_TRANSITIONS = {
    "assessing": {"assessing", "awaiting_selection", "investigating", "paused"},
    "awaiting_selection": {"awaiting_selection", "investigating", "paused"},
    "investigating": {"investigating", "awaiting_maintainer", "implementing", "ready_for_pr", "paused", "closed"},
    "awaiting_maintainer": {"awaiting_maintainer", "investigating", "implementing", "closed", "paused"},
    "implementing": {"implementing", "ready_for_pr", "awaiting_maintainer", "paused", "closed"},
    "ready_for_pr": {"ready_for_pr", "reviewing", "implementing", "paused", "closed"},
    "reviewing": {"reviewing", "implementing", "merged", "closed", "paused"},
    "merged": {"merged", "paused"}, "closed": {"closed", "investigating", "paused"},
    "paused": set(PHASES),
}
FIELDS = {
    "phase": str, "summary": str, "next_action": str, "blockers": list,
    "candidates": list, "selected_issue": str, "selected_pr": str,
    "checkout": dict, "profile": dict, "authorization": list, "evidence": list,
    "checks": list, "review_cursor": dict, "artifacts": list, "outcome": dict,
}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

SECURITY_TERMS = re.compile(r"(任意代码执行|远程代码执行|权限提升|认证绕过|越权|数据泄露|供应链|命令注入|sql注入|xss|rce|cve|credential leak|arbitrary code)", re.I)

def looks_security_sensitive(text):
    """Conservative routing hint; it never proves a vulnerability."""
    return bool(SECURITY_TERMS.search(text or ""))


def parse_repo(value):
    value = value.strip()
    if "://" in value:
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or parsed.netloc.lower() != "github.com"
                or parsed.query or parsed.fragment):
            raise ValueError("Use owner/repo or an HTTPS github.com repository URL.")
        value = parsed.path.strip("/")
    else:
        value = value.rstrip("/")
    if value.endswith(".git"):
        value = value[:-4]
    parts = value.split("/")
    if (len(parts) != 2 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", parts[0])
            or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", parts[1])
            or parts[1] in (".", "..") or parts[1].endswith(".")):
        raise ValueError("Expected owner/repo, not an issue URL, filesystem path or command.")
    return "/".join(parts)


def default_root():
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    return home / "open-source-contributions"


def case_directory(root, repo, case):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", case):
        raise ValueError("Case must contain 1-64 lowercase letters, digits or hyphens.")
    root = Path(root).expanduser().resolve()
    target = root.joinpath("github.com", *parse_repo(repo).lower().split("/"), case).resolve()
    if root not in target.parents:
        raise ValueError("Record path escapes the selected root.")
    if any((parent / ".git").exists() for parent in (target, *target.parents)):
        raise ValueError("Records must be outside a Git checkout; choose a personal --root.")
    return target


@contextmanager
def record_lock(directory):
    lock = directory / ".record.lock"
    try:
        handle = lock.open("x", encoding="utf-8")
    except FileExistsError:
        raise ValueError("Record is locked. Verify the writer has stopped before removing .record.lock.")
    try:
        with handle:
            handle.write(str(os.getpid()))
        yield
    finally:
        lock.unlink()


def write_json(path, data):
    fd, temporary = tempfile.mkstemp(prefix=".record-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def initialize(directory, repo, case):
    directory.mkdir(parents=True, exist_ok=True)
    with record_lock(directory):
        path = directory / "record.json"
        if path.exists():
            raise ValueError("Record already exists; use show/update or choose a different case.")
        timestamp = now()
        data = {
            "schema_version": 1, "repo": parse_repo(repo), "case": case,
            "created_at": timestamp, "updated_at": timestamp, "revision": 0,
            "phase": "assessing", "summary": "", "next_action": "Inspect repository evidence.",
            "blockers": [], "candidates": [], "selected_issue": "", "selected_pr": "",
            "checkout": {}, "profile": {}, "authorization": [], "evidence": [],
            "checks": [], "review_cursor": {}, "artifacts": [], "outcome": {},
            "history": [{"at": timestamp, "revision": 0, "phase": "assessing", "summary": "Initialized"}],
        }
        write_json(path, data)
        return data


def read_record(directory, repo, case):
    data = json.loads((directory / "record.json").read_text(encoding="utf-8-sig"))
    if (data.get("schema_version") != 1 or data.get("repo", "").lower() != parse_repo(repo).lower()
            or data.get("case") != case or not isinstance(data.get("revision"), int)):
        raise ValueError("Record schema or repository/case identity does not match.")
    return data


def validate_record(data):
    """Return human-readable consistency errors without changing the record."""
    errors = []
    phase = data.get("phase")
    checkout = data.get("checkout") or {}
    outcome = data.get("outcome") or {}
    if phase not in PHASES:
        errors.append("phase is unknown")
    if phase == "merged" and not (data.get("selected_pr") and (outcome.get("merged_at") or outcome.get("merge_commit"))):
        errors.append("merged requires selected_pr and outcome.merged_at or outcome.merge_commit")
    if phase == "reviewing" and not ((data.get("selected_pr")) and ((data.get("review_cursor") or {}).get("head_sha"))):
        errors.append("reviewing requires selected_pr and review_cursor.head_sha")
    if phase == "ready_for_pr":
        if not checkout.get("branch") or not checkout.get("commit"):
            errors.append("ready_for_pr requires checkout.branch and checkout.commit")
        if not data.get("checks"):
            errors.append("ready_for_pr requires at least one check")
    if phase in {"implementing", "ready_for_pr", "reviewing", "merged"} and not (checkout.get("branch") and checkout.get("commit")):
        errors.append(f"{phase} requires checkout.branch and checkout.commit")
    for field in ("evidence", "checks", "authorization"):
        for index, item in enumerate(data.get(field) or []):
            if isinstance(item, dict) and "id" not in item:
                errors.append(f"{field}[{index}] is missing stable id")
            if field == "authorization" and isinstance(item, dict):
                missing = [key for key in ("action", "target", "scope", "source", "status") if not item.get(key)]
                if missing: errors.append(f"authorization[{index}] missing: {', '.join(missing)}")
    return errors


def update(directory, repo, case, patch, expected_revision):
    if not isinstance(patch, dict) or not patch:
        raise ValueError("Patch must be a nonempty JSON object.")
    unknown = set(patch) - set(FIELDS)
    if unknown:
        raise ValueError("Unknown or immutable fields: " + ", ".join(sorted(unknown)))
    for key, value in patch.items():
        if not isinstance(value, FIELDS[key]):
            raise ValueError(f"Wrong type for {key}; expected {FIELDS[key].__name__}.")
    if "phase" in patch and patch["phase"] not in PHASES:
        raise ValueError("Unknown phase: " + patch["phase"])
    with record_lock(directory):
        data = read_record(directory, repo, case)
        if data["revision"] != expected_revision:
            raise ValueError("Revision changed; show the current record and reconcile before updating.")
        if "phase" in patch and patch["phase"] not in ALLOWED_TRANSITIONS.get(data["phase"], set()):
            raise ValueError(f"Invalid phase transition: {data['phase']} -> {patch['phase']}")
        data.update(patch)
        data["revision"] += 1
        data["updated_at"] = now()
        data["history"].append({
            "at": data["updated_at"], "revision": data["revision"],
            "phase": data["phase"], "summary": data["summary"],
        })
        write_json(directory / "record.json", data)
        return data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "show", "update", "validate", "path"))
    parser.add_argument("repo", help="owner/repo or https://github.com/owner/repo")
    parser.add_argument("--case", default="assessment", help="assessment, issue-123, pr-456, etc.")
    parser.add_argument("--root", type=Path, default=default_root(), help="Personal records root, outside upstream checkout")
    parser.add_argument("--patch-file", type=Path, help="UTF-8 JSON; specified fields replace previous values")
    parser.add_argument("--expected-revision", type=int)
    args = parser.parse_args(argv)
    try:
        directory = case_directory(args.root, args.repo, args.case)
        if args.command == "path":
            print(directory)
            return 0
        if args.command == "init":
            data = initialize(directory, args.repo, args.case)
        elif args.command == "show":
            data = read_record(directory, args.repo, args.case)
        elif args.command == "validate":
            data = read_record(directory, args.repo, args.case)
            errors = validate_record(data)
            print(json.dumps({"record_path": str(directory / "record.json"), "valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
            return 0 if not errors else 2
        else:
            if args.patch_file is None or args.expected_revision is None:
                raise ValueError("update requires --patch-file and --expected-revision.")
            patch = json.loads(args.patch_file.read_text(encoding="utf-8-sig"))
            data = update(directory, args.repo, args.case, patch, args.expected_revision)
        print(json.dumps({"record_path": str(directory / "record.json"), "record": data}, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Read-only Git preflight for contribution branches and push targets."""
import argparse, json, subprocess, sys
from pathlib import Path

def run(cwd, *args):
    p = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True)
    return {"command": "git " + " ".join(args), "returncode": p.returncode,
            "stdout": p.stdout.strip(), "stderr": p.stderr.strip()}

def collect(path, base_repo=None, base_branch=None, push_remote=None):
    path = str(Path(path).resolve())
    checks = {}
    for name, args in {
        "root": ("rev-parse", "--show-toplevel"), "branch": ("branch", "--show-current"),
        "head": ("rev-parse", "HEAD"), "status": ("status", "--short"),
        "remotes": ("remote", "-v"), "tracking": ("status", "--porcelain=v2", "-b"),
        "commits": ("log", "--oneline", "-20"),
    }.items(): checks[name] = run(path, *args)
    remotes = {}
    for line in checks["remotes"]["stdout"].splitlines():
        parts = line.split()
        if len(parts) >= 3: remotes.setdefault(parts[0], {})[parts[2]] = parts[1]
    push_targets = [v.get("push") for v in remotes.values() if v.get("push")]
    warnings = []
    if len(push_targets) != len(set(push_targets)): warnings.append("duplicate push URL detected")
    if len(push_targets) > 1: warnings.append("multiple push URLs detected; use explicit remote and branch")
    if checks["status"]["stdout"]: warnings.append("working tree has uncommitted changes")
    if not checks["branch"]["stdout"]: warnings.append("detached HEAD")
    if push_remote and push_remote not in remotes: warnings.append(f"push remote not found: {push_remote}")
    if base_branch and not base_branch.strip(): warnings.append("base branch is empty")
    if base_repo and not any(base_repo.lower() in (u or "").lower() for v in remotes.values() for u in v.values()):
        warnings.append("base repository is not present in configured remotes")
    return {"path": path, "base_repo": base_repo, "base_branch": base_branch, "push_remote": push_remote,
            "checks": checks, "remotes": remotes, "push_targets": push_targets, "warnings": warnings,
            "safe_to_push": not warnings and checks["head"]["returncode"] == 0}

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__); p.add_argument("path", nargs="?", default=".")
    p.add_argument("--base-repo"); p.add_argument("--base-branch"); p.add_argument("--push-remote")
    args = p.parse_args(argv)
    try: print(json.dumps(collect(args.path, args.base_repo, args.base_branch, args.push_remote), ensure_ascii=False, indent=2)); return 0
    except (OSError, ValueError) as e: print(f"Error: {e}", file=sys.stderr); return 2
if __name__ == "__main__": sys.exit(main())

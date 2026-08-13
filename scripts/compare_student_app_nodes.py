from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


FORMAT = "student-app-node-status/v1"


def _read(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError(f"Unsupported node status: {path}")
    return data


def compare(development: dict, production: dict) -> dict:
    failures: list[str] = []
    warnings: list[str] = []
    expected = {
        "Development": (development, "dev-app.5a-math.com", 8004),
        "Production": (production, "app.5a-math.com", 8003),
    }
    for role, (node, host, port) in expected.items():
        if node.get("role") != role:
            failures.append(f"{role.lower()}_role_mismatch")
        public = node.get("public") if isinstance(node.get("public"), dict) else {}
        if public.get("expectedHost") != host or public.get("originPort") != port:
            failures.append(f"{role.lower()}_host_or_port_mismatch")
        if public.get("localStatus") != 200:
            failures.append(f"{role.lower()}_local_app_not_ready")
        if public.get("crossHostStatus") != 404:
            failures.append(f"{role.lower()}_cross_host_not_hidden")
        privacy = node.get("privacy") if isinstance(node.get("privacy"), dict) else {}
        if any(privacy.get(key) for key in ("containsRuntimeContents", "containsCanarySids", "containsCredentials", "containsVapidKey")):
            failures.append(f"{role.lower()}_receipt_privacy_failure")
    if development.get("computer") == production.get("computer"):
        failures.append("roles_share_computer")
    if str(development.get("serverRoot", "")).casefold() == str(production.get("serverRoot", "")).casefold():
        failures.append("roles_share_server_root")
    dev_ingress = development.get("cloudflared", {}).get("ingress", [])
    prod_ingress = production.get("cloudflared", {}).get("ingress", [])
    if not any(row.get("hostname") == "dev-app.5a-math.com" for row in dev_ingress if isinstance(row, dict)):
        failures.append("development_tunnel_missing")
    if not any(row.get("hostname") == "app.5a-math.com" for row in prod_ingress if isinstance(row, dict)):
        failures.append("production_tunnel_missing")
    dev_runtime = development.get("runtimeFingerprints", {})
    prod_runtime = production.get("runtimeFingerprints", {})
    identical = []
    for name in ("students.json", "auth_accounts.json", "app.sqlite", "updates.json"):
        left = dev_runtime.get(name) if isinstance(dev_runtime, dict) else None
        right = prod_runtime.get(name) if isinstance(prod_runtime, dict) else None
        if isinstance(left, dict) and isinstance(right, dict) and left.get("sha256") == right.get("sha256"):
            identical.append(name)
    if identical:
        warnings.append("runtime_fingerprints_match:" + ",".join(identical))
    dev_commit = development.get("source", {}).get("commit")
    prod_commit = production.get("source", {}).get("commit")
    if dev_commit and prod_commit and dev_commit != prod_commit:
        warnings.append("source_commits_differ")
    return {"ok": not failures, "failures": failures, "warnings": warnings}


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare development and production node receipts.")
    parser.add_argument("development", type=Path)
    parser.add_argument("production", type=Path)
    args = parser.parse_args()
    try:
        result = compare(_read(args.development), _read(args.production))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

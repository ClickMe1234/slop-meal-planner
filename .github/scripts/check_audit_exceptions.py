#!/usr/bin/env python3
"""Validate the small, explicit dependency-audit exception list.

The audit output is intentionally printed by CI before this script runs.  An
exception therefore suppresses a gate without hiding the raw advisory from
the build log, and the date check makes an overdue exception fail closed.
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
import sys


def _today() -> date:
    override = os.environ.get("AUDIT_EXCEPTION_DATE")
    return date.fromisoformat(override) if override else date.today()


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict) or not isinstance(value.get("exceptions"), list):
        raise ValueError("audit exception policy must contain an exceptions list")
    return value


def _vulnerabilities(audit: object) -> list[tuple[str, str, str]]:
    if isinstance(audit, dict):
        dependencies = audit.get("dependencies", [])
    elif isinstance(audit, list):
        dependencies = audit
    else:
        dependencies = []
    findings: list[tuple[str, str, str]] = []
    for dependency in dependencies:
        if not isinstance(dependency, dict):
            continue
        package = str(dependency.get("name", ""))
        version = str(dependency.get("version", ""))
        for vulnerability in dependency.get("vulns", []) or []:
            if isinstance(vulnerability, dict):
                advisory = str(vulnerability.get("id", ""))
            else:
                advisory = str(vulnerability)
            findings.append((package, version, advisory))
    return findings


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: check_audit_exceptions.py AUDIT.json POLICY.json", file=sys.stderr)
        return 64
    audit_path, policy_path = map(Path, argv[1:])
    try:
        with audit_path.open(encoding="utf-8") as handle:
            audit = json.load(handle)
        policy = _load(policy_path)
        today = _today()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Invalid dependency audit policy/input: {exc}", file=sys.stderr)
        return 2

    active: dict[tuple[str, str], dict] = {}
    for exception in policy["exceptions"]:
        if not isinstance(exception, dict):
            print("Invalid dependency audit exception entry", file=sys.stderr)
            return 2
        package = str(exception.get("package", ""))
        expires = exception.get("expires_on")
        ids = exception.get("ids")
        try:
            expiry = date.fromisoformat(str(expires))
        except (TypeError, ValueError):
            print(f"Invalid expiry for dependency exception {package!r}", file=sys.stderr)
            return 2
        if not package or not isinstance(ids, list) or not ids:
            print("Dependency exceptions require a package and advisory IDs", file=sys.stderr)
            return 2
        if today >= expiry:
            print(f"Dependency audit exception for {package} expired on {expiry}", file=sys.stderr)
            return 1
        for advisory in ids:
            active[(package.casefold(), str(advisory))] = exception

    unexpected: list[tuple[str, str, str]] = []
    for finding in _vulnerabilities(audit):
        package, version, advisory = finding
        if (package.casefold(), advisory) not in active:
            unexpected.append(finding)
    if unexpected:
        print("Unapproved dependency vulnerabilities remain:", file=sys.stderr)
        for package, version, advisory in unexpected:
            print(f"  {package}=={version}: {advisory}", file=sys.stderr)
        return 1
    if _vulnerabilities(audit):
        print("All dependency vulnerabilities are covered by active, scoped exceptions.")
    else:
        print("Dependency audit is clean.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

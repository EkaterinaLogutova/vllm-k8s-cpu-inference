#!/usr/bin/env python3
"""Verify that requirements.txt exactly describes the image Python runtime."""

from __future__ import annotations

import importlib.metadata
import re
import sys
from pathlib import Path


PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s]+)$")


def canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def read_lock(path: Path) -> dict[str, tuple[str, str]]:
    expected: dict[str, tuple[str, str]] = {}
    for number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = PIN.fullmatch(line)
        if not match:
            raise ValueError(f"{path}:{number}: dependency is not exactly pinned: {line}")
        name, version = match.groups()
        expected[canonical_name(name)] = (name, version)
    return expected


def installed_packages() -> dict[str, tuple[str, str]]:
    packages: dict[str, tuple[str, str]] = {}
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name")
        if name:
            packages[canonical_name(name)] = (name, distribution.version)
    return packages


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: verify_runtime_lock.py REQUIREMENTS", file=sys.stderr)
        return 2

    expected = read_lock(Path(sys.argv[1]))
    actual = installed_packages()
    problems: list[str] = []

    for key, (name, version) in sorted(expected.items()):
        if key not in actual:
            problems.append(f"missing: {name}=={version}")
        elif actual[key][1] != version:
            problems.append(
                f"version mismatch: {name} expected {version}, installed {actual[key][1]}"
            )

    for key, (name, version) in sorted(actual.items()):
        if key not in expected:
            problems.append(f"not locked: {name}=={version}")

    if problems:
        print("runtime lock verification failed:", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
        return 1

    print(f"runtime lock verified: {len(expected)} packages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

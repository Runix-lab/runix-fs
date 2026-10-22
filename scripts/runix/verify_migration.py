#!/usr/bin/env python3
"""Verify Runix fork provenance and prevent inherited upstream publishing.

Run with Python 3.11+ and PyYAML 6.0.2. No network or credentials required.
Licensed under the repository's Apache-2.0 license.
"""

import re
import subprocess
from pathlib import Path

import yaml

BASELINE = "7d476508e2cd608a1aaaf7837999f52ab633811e"
PUBLISHERS = (
    "build-compile-image.yml",
    "build-csi-image.yml",
    "build-java-sdk.yml",
    "build-runtime-image.yml",
    "build-tests-image.yml",
    "release.yml",
    "trigger-helm-release.yml",
)
GUARD = "github.repository == 'CurvineIO/curvine'"


def verify(root: Path) -> list[str]:
    errors = []

    def original(name):
        return subprocess.check_output(
            ["git", "show", f"{BASELINE}:{name}"], cwd=root
        )

    if (root / "LICENSE").read_bytes() != original("LICENSE"):
        errors.append("Upstream LICENSE changed")
    if (root / "README.upstream.md").read_bytes() != original("README.md"):
        errors.append("Preserved upstream README differs from baseline")
    notice = (root / "NOTICE").read_text()
    if not all(value in notice for value in ("Curvine", "OPPO", "Apache", "Runix")):
        errors.append("NOTICE is missing source attribution")

    for name in PUBLISHERS:
        workflow = yaml.safe_load((root / ".github/workflows" / name).read_text())
        upstream = yaml.safe_load(original(f".github/workflows/{name}"))
        for job_name, job in workflow["jobs"].items():
            condition = job.get("if", "")
            inherited = upstream["jobs"].get(job_name, {}).get("if", "").strip()
            if inherited.startswith("${{") and inherited.endswith("}}"):
                inherited = inherited[3:-2].strip()
            # Exact comparison retains the original condition and prevents an
            # unbalanced expression from adding an outer OR to bypass the guard.
            expected = (
                "${{ " + GUARD + " && (" + inherited + ") }}"
                if inherited else GUARD
            )
            if condition != expected:
                errors.append(f"Unguarded inherited publisher: {name}:{job_name}")

    for name in ("README.md", "specs/README.md"):
        for target in re.findall(r"\]\(([^)]+)\)", (root / name).read_text()):
            if "://" in target or target.startswith("#"):
                continue
            if not (root / name).parent.joinpath(target.split("#")[0]).exists():
                errors.append(f"Broken local documentation link: {name}:{target}")
    return errors


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    failures = verify(root)
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        raise SystemExit(1)
    print("PASS: provenance, attribution, documentation and upstream publication guards")

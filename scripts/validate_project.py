"""Fast offline checks that do not require Docker, kubectl or a cluster."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = (
    "Dockerfile",
    "Dockerfile.downloader",
    "requirements.txt",
    "requirements-downloader.txt",
    "app/entrypoint.sh",
    "app/privacy_middleware.py",
    "scripts/download_model.py",
    "scripts/load_test.py",
    "scripts/verify_runtime_lock.py",
    "k8s/base/deployment.yaml",
    "k8s/base/pvc.yaml",
    "k8s/base/configmap.yaml",
    "k8s/base/service.yaml",
    "k8s/overlays/minikube/kustomization.yaml",
)


def check(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def main() -> int:
    errors: list[str] = []
    for relative in REQUIRED_FILES:
        check((ROOT / relative).is_file(), f"missing {relative}", errors)

    for relative in (
        "app/privacy_middleware.py",
        "scripts/download_model.py",
        "scripts/load_test.py",
        "scripts/verify_runtime_lock.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        try:
            ast.parse(source, filename=relative)
        except SyntaxError as error:
            errors.append(f"invalid Python in {relative}: {error}")

    for relative in ("requirements.txt", "requirements-downloader.txt"):
        for number, line in enumerate((ROOT / relative).read_text(encoding="utf-8").splitlines(), 1):
            value = line.strip()
            if value and not value.startswith("#"):
                check(
                    bool(re.fullmatch(r"[A-Za-z0-9_.-]+==[^\s]+", value)),
                    f"{relative}:{number} is not exactly pinned: {value}",
                    errors,
                )

    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    check("v0.27.0-x86_64" in dockerfile or "v${VLLM_VERSION}-x86_64" in dockerfile, "vLLM image is not pinned", errors)
    check("USER 10001:10001" in dockerfile, "main image is not rootless", errors)

    deployment = (ROOT / "k8s/base/deployment.yaml").read_text(encoding="utf-8")
    for token in (
        "initContainers:",
        "persistentVolumeClaim:",
        "runAsNonRoot: true",
        "readOnlyRootFilesystem: true",
        "allowPrivilegeEscalation: false",
        "secretKeyRef:",
        "configMapRef:",
    ):
        check(token in deployment, f"deployment misses {token}", errors)

    middleware = (ROOT / "app/privacy_middleware.py").read_text(encoding="utf-8")
    check("await receive(" not in middleware, "privacy middleware reads request bodies", errors)
    check("compare_digest" in middleware, "token comparison is not constant-time", errors)

    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    check(
        "k8s/overlays/minikube/secret.env" in gitignore,
        "real secret.env is not excluded by .gitignore",
        errors,
    )

    if errors:
        print("validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("offline validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


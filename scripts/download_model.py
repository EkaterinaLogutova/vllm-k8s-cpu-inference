"""Idempotently download one Hugging Face model into a mounted PVC."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

from huggingface_hub import snapshot_download

SAFE_REPO_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")
SAFE_SUBDIR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} must not be empty")
    return value


def main() -> int:
    model_id = required("MODEL_ID")
    revision = required("MODEL_REVISION")
    model_root = Path(os.environ.get("MODEL_MOUNT", "/models")).resolve()
    model_subdir = os.environ.get("MODEL_SUBDIR", "model").strip()
    token = os.environ.get("HF_TOKEN", "").strip() or None

    if not SAFE_REPO_ID.fullmatch(model_id):
        raise ValueError("MODEL_ID must have the form organization/model")
    if not SAFE_SUBDIR.fullmatch(model_subdir):
        raise ValueError("MODEL_SUBDIR contains unsafe characters")

    target = (model_root / model_subdir).resolve()
    if model_root not in target.parents:
        raise ValueError("MODEL_SUBDIR escapes MODEL_MOUNT")

    target.mkdir(parents=True, exist_ok=True)
    marker = target / ".download-complete.json"
    expected = {"model_id": model_id, "revision": revision}

    if marker.is_file() and (target / "config.json").is_file():
        current = json.loads(marker.read_text(encoding="utf-8"))
        if all(current.get(key) == value for key, value in expected.items()):
            print(f"model cache hit: {model_id}@{revision}")
            return 0

    print(f"downloading model metadata and weights: {model_id}@{revision}")
    snapshot_download(
        repo_id=model_id,
        revision=revision,
        local_dir=target,
        token=token,
        resume_download=True,
    )

    if not (target / "config.json").is_file():
        raise RuntimeError("download finished without config.json")

    completed = {
        **expected,
        "completed_unix": int(time.time()),
    }
    temporary = target / ".download-complete.json.tmp"
    temporary.write_text(json.dumps(completed, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(marker)
    print(f"model cache populated: {target}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"model download failed: {type(error).__name__}: {error}", file=sys.stderr)
        raise


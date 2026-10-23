"""Small dependency-free streaming benchmark for the vLLM Chat API."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


SHORT_PROMPT = "Кратко объясни, что такое PagedAttention. Ответь в двух предложениях."
LONG_PROMPT = (
    "Ты анализируешь архитектуру сервиса инференса. "
    "Учитывай CPU, Kubernetes, непривилегированные контейнеры, PVC, "
    "инициализирующий контейнер, конфигурацию, секреты и наблюдаемость. " * 20
    + "Сформулируй пять практических рекомендаций без повторов."
)


@dataclass(frozen=True)
class Sample:
    ttft_seconds: float
    latency_seconds: float
    completion_tokens: int


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return math.nan
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def one_request(
    url: str,
    api_key: str,
    model: str,
    prompt: str,
    max_tokens: int,
    timeout: float,
) -> Sample:
    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{url.rstrip('/')}/v1/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    started = time.perf_counter()
    first_token_at: float | None = None
    completion_tokens = 0
    with urllib.request.urlopen(request, timeout=timeout) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8").strip()
            if not line.startswith("data: "):
                continue
            data = line[6:]
            if data == "[DONE]":
                break
            chunk = json.loads(data)
            usage = chunk.get("usage") or {}
            completion_tokens = max(completion_tokens, int(usage.get("completion_tokens") or 0))
            for choice in chunk.get("choices") or []:
                delta = choice.get("delta") or {}
                if delta.get("content") and first_token_at is None:
                    first_token_at = time.perf_counter()

    finished = time.perf_counter()
    if first_token_at is None:
        raise RuntimeError("stream ended without a generated token")
    return Sample(first_token_at - started, finished - started, completion_tokens)


def run_case(args: argparse.Namespace, name: str, prompt: str) -> dict[str, object]:
    started = time.perf_counter()
    samples: list[Sample] = []
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [
            pool.submit(
                one_request,
                args.base_url,
                args.api_key,
                args.model,
                prompt,
                args.max_tokens,
                args.timeout,
            )
            for _ in range(args.requests)
        ]
        for future in as_completed(futures):
            try:
                samples.append(future.result())
            except (OSError, ValueError, RuntimeError, urllib.error.HTTPError) as error:
                errors.append(f"{type(error).__name__}: {error}")
    wall_seconds = time.perf_counter() - started
    ttft = [sample.ttft_seconds for sample in samples]
    latency = [sample.latency_seconds for sample in samples]
    tokens = sum(sample.completion_tokens for sample in samples)
    return {
        "case": name,
        "prompt_chars": len(prompt),
        "requests": args.requests,
        "concurrency": args.concurrency,
        "successful": len(samples),
        "failed": len(errors),
        "ttft_p50_seconds": percentile(ttft, 0.50),
        "ttft_p95_seconds": percentile(ttft, 0.95),
        "latency_mean_seconds": statistics.fmean(latency) if latency else math.nan,
        "latency_p95_seconds": percentile(latency, 0.95),
        "throughput_tokens_per_second": tokens / wall_seconds if wall_seconds else math.nan,
        "throughput_requests_per_second": len(samples) / wall_seconds if wall_seconds else math.nan,
        "wall_seconds": wall_seconds,
        "samples": [asdict(sample) for sample in samples],
        "errors": errors,
    }


def markdown(results: list[dict[str, object]]) -> str:
    rows = [
        "| Prompt | Success | TTFT p50, s | TTFT p95, s | Latency mean, s | Latency p95, s | Tokens/s | Requests/s |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for result in results:
        rows.append(
            "| {case} | {successful}/{requests} | {ttft_p50_seconds:.3f} | "
            "{ttft_p95_seconds:.3f} | {latency_mean_seconds:.3f} | "
            "{latency_p95_seconds:.3f} | {throughput_tokens_per_second:.2f} | "
            "{throughput_requests_per_second:.2f} |".format(**result)
        )
    return "\n".join(rows) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--model", default="qwen2.5-0.5b-instruct")
    parser.add_argument("--requests", type=int, default=12)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--max-tokens", type=int, default=64)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--output-dir", type=Path, default=Path("benchmark-results"))
    args = parser.parse_args()
    if args.requests < 1 or args.concurrency < 1 or args.max_tokens < 1:
        parser.error("requests, concurrency and max-tokens must be positive")
    return args


def main() -> int:
    args = parse_args()
    results = [
        run_case(args, "short", SHORT_PROMPT),
        run_case(args, "long", LONG_PROMPT),
    ]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "model": args.model,
        "max_tokens": args.max_tokens,
        "results": results,
    }
    json_path = args.output_dir / f"benchmark-{timestamp}.json"
    md_path = args.output_dir / f"benchmark-{timestamp}.md"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    table = markdown(results)
    md_path.write_text(table, encoding="utf-8")
    print(table, end="")
    print(f"JSON: {json_path}")
    print(f"Markdown: {md_path}")
    return 1 if any(result["failed"] for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())


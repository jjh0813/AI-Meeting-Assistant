import argparse
import json
import statistics as st
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.core.prompts import ANALYSIS_PROMPT  # noqa: E402
from app.services.masking import mask_text  # noqa: E402

SAMPLES_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "samples" / "meeting_samples.json"
)


def _call_ollama(prompt: str):
    url = settings.ollama_base_url + "/api/generate"
    body = {
        "model": settings.llm_model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
    }
    start = time.time()
    response = httpx.post(url, json=body, timeout=180)
    response.raise_for_status()
    data = response.json()
    latency = time.time() - start
    return latency, data.get("prompt_eval_count", 0), data.get("eval_count", 0)


def _percentile(values, ratio):
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * ratio))
    return round(ordered[index], 2)


def masking_stats(samples):
    total_pii = masked_pii = total_masks = false_positives = 0
    for sample in samples:
        _, found = mask_text(sample["text"])
        masked_values = [f["original_value"] for f in found]
        expected = set(sample["expected_names"]) | set(sample["expected_phones"])
        for item in expected:
            total_pii += 1
            if any(item == mv or item in mv for mv in masked_values):
                masked_pii += 1
        for mv in masked_values:
            total_masks += 1
            if not any(mv == item or mv in item for item in expected):
                false_positives += 1
    recall = masked_pii / total_pii if total_pii else 0
    precision = (total_masks - false_positives) / total_masks if total_masks else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0
    return {
        "total_pii": total_pii,
        "masked_pii": masked_pii,
        "recall": round(recall, 3),
        "precision": round(precision, 3),
        "f1": round(f1, 3),
        "total_masks": total_masks,
        "false_positives": false_positives,
    }


def llm_stats(samples, n):
    latencies, prompt_tokens, completion_tokens = [], [], []
    ok = errors = 0
    for sample in samples[:n]:
        masked, _ = mask_text(sample["text"])
        prompt = ANALYSIS_PROMPT.format(content=masked)
        try:
            latency, ptok, ctok = _call_ollama(prompt)
            latencies.append(latency)
            prompt_tokens.append(ptok)
            completion_tokens.append(ctok)
            ok += 1
        except Exception:
            errors += 1
    avg_p = st.mean(prompt_tokens) if prompt_tokens else 0
    avg_c = st.mean(completion_tokens) if completion_tokens else 0
    return {
        "llm_runs": ok,
        "errors": errors,
        "error_rate": round(errors / max(1, ok + errors), 3),
        "latency_avg_s": round(st.mean(latencies), 2) if latencies else 0,
        "latency_p95_s": _percentile(latencies, 0.95),
        "avg_prompt_tokens": round(avg_p, 1),
        "avg_completion_tokens": round(avg_c, 1),
        "avg_total_tokens": round(avg_p + avg_c, 1),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm-samples", type=int, default=20)
    parser.add_argument("--masking-only", action="store_true")
    args = parser.parse_args()

    samples = json.loads(SAMPLES_PATH.read_text(encoding="utf-8"))
    report = {"num_samples": len(samples), "masking": masking_stats(samples)}
    if not args.masking_only:
        report["llm"] = llm_stats(samples, args.llm_samples)

    out = SAMPLES_PATH.parent / "benchmark_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("saved ->", out)


if __name__ == "__main__":
    main()

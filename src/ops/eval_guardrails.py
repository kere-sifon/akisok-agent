from __future__ import annotations

import argparse
from typing import Any

from src.config import load_settings
from src.db.mongo_client import ReviewQueueStore

DECIDED = {"approved", "rejected"}


def _flagged(item: dict[str, Any]) -> bool:
    return bool(item.get("guardrail_flags"))


def confusion_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    decided = [item for item in items if item.get("status") in DECIDED]
    tp = fp = fn = tn = 0
    for item in decided:
        flagged = _flagged(item)
        rejected = item.get("status") == "rejected"
        if flagged and rejected:
            tp += 1
        elif flagged and not rejected:
            fp += 1
        elif not flagged and rejected:
            fn += 1
        else:
            tn += 1
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "n": len(decided)}


def precision_recall(counts: dict[str, int]) -> dict[str, float | None]:
    tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
    precision = (tp / (tp + fp)) if (tp + fp) else None
    recall = (tp / (tp + fn)) if (tp + fn) else None
    return {"precision": precision, "recall": recall}


def evaluate_guardrails(
    items: list[dict[str, Any]],
    *,
    min_samples: int = 20,
) -> dict[str, Any]:
    counts = confusion_counts(items)
    rates = precision_recall(counts)
    return {
        **counts,
        **rates,
        "small_sample": counts["n"] < min_samples,
        "min_samples": min_samples,
    }


def format_guardrail_report(result: dict[str, Any]) -> str:
    precision = result["precision"]
    recall = result["recall"]
    lines = [
        f"Decided items:  {result['n']}",
        f"TP / FP / FN / TN: {result['tp']} / {result['fp']} / {result['fn']} / {result['tn']}",
        f"Precision:      {'n/a' if precision is None else f'{precision:.2f}'}",
        f"Recall:         {'n/a' if recall is None else f'{recall:.2f}'}",
    ]
    if result["small_sample"]:
        lines.append(
            f"Warning: sample is too small to draw conclusions "
            f"({result['n']} < {result['min_samples']} decided items)."
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Guardrail precision/recall vs human approve/reject.")
    parser.add_argument("--min-samples", type=int, default=20)
    args = parser.parse_args(argv)
    settings = load_settings()
    store = ReviewQueueStore(uri=settings.mongodb_uri, db_name=settings.mongodb_db_name)
    result = evaluate_guardrails(store.list_review_items(), min_samples=args.min_samples)
    print(format_guardrail_report(result), end="")


if __name__ == "__main__":
    main()

from __future__ import annotations

from src.ops.eval_guardrails import evaluate_guardrails, format_guardrail_report


def _item(status: str, flags: list[str]) -> dict:
    return {"status": status, "guardrail_flags": flags}


def test_confusion_matrix_and_rates() -> None:
    items = [
        _item("rejected", ["sensitive_topic"]),  # TP
        _item("rejected", ["broken_source_link"]),  # TP
        _item("approved", ["likely_duplicate"]),  # FP
        _item("rejected", []),  # FN
        _item("approved", []),  # TN
        _item("pending", ["sensitive_topic"]),  # ignored
        _item("flagged", []),  # ignored
    ]
    result = evaluate_guardrails(items, min_samples=3)

    assert result["tp"] == 2
    assert result["fp"] == 1
    assert result["fn"] == 1
    assert result["tn"] == 1
    assert result["n"] == 5
    assert result["precision"] == pytest_precision(2, 1)
    assert result["recall"] == pytest_precision(2, 1)
    assert result["small_sample"] is False


def pytest_precision(tp: int, other: int) -> float:
    return tp / (tp + other)


def test_small_sample_warning() -> None:
    items = [_item("approved", []), _item("rejected", ["sensitive_topic"])]
    result = evaluate_guardrails(items, min_samples=20)
    assert result["n"] == 2
    assert result["small_sample"] is True
    report = format_guardrail_report(result)
    assert "too small to draw conclusions" in report
    assert "TP / FP / FN / TN" in report

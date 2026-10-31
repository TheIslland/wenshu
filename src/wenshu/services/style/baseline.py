"""Personal baseline: mean/std per metric, then z-scores so discipline habits
(author X always writes short sentences) do not become false alarms.
"""

from __future__ import annotations

import statistics
from typing import Any

from ...errors import ValidationFailed
from . import metrics

BASELINE_VERSION = 1
MIN_SAMPLES = 3


def build(texts: list[str] | None) -> dict[str, Any]:
    """Build `{version, samples, metrics: {key: {mean, std, n}}, warnings}`."""
    cleaned = [text for text in (texts or []) if text and text.strip()]
    if not cleaned:
        raise ValidationFailed("至少需要一篇本人文本才能建立基线。")
    samples = [metrics.compute(text) for text in cleaned]
    keys = sorted({key for sample in samples for key in sample})
    table: dict[str, dict[str, float]] = {}
    for key in keys:
        values = [float(sample.get(key, 0.0)) for sample in samples]
        table[key] = {
            "mean": round(statistics.fmean(values), 4),
            "std": round(statistics.pstdev(values) if len(values) > 1 else 0.0, 4),
            "n": float(len(values)),
        }
    warnings: list[str] = []
    if len(cleaned) < MIN_SAMPLES:
        warnings.append(
            f"只提供了 {len(cleaned)} 篇样本：建议 3–5 篇本人已发表或认可的文本，阈值才稳。"
        )
    return {
        "version": BASELINE_VERSION,
        "samples": len(cleaned),
        "chars": float(sum(metrics.density_unit(text) for text in cleaned)),
        "metrics": table,
        "warnings": warnings,
    }


def score(values: dict[str, float], baseline: dict[str, Any] | None) -> dict[str, Any]:
    """z-score every metric the baseline knows about, and list 1.5σ deviations."""
    table = (baseline or {}).get("metrics") or {}
    z_scores: dict[str, float] = {}
    deviations: list[dict[str, float | str]] = []
    for key, stats in table.items():
        if key not in values:
            continue
        mean = float(stats.get("mean", 0.0))
        std = float(stats.get("std", 0.0))
        value = float(values[key])
        if std <= 1e-9:
            # Rounded means must not turn "same as usual" into a 3σ outlier.
            tolerance = max(1e-3, abs(mean) * 1e-3)
            z_value = 0.0 if abs(value - mean) <= tolerance else 3.0
        else:
            z_value = (value - mean) / std
        z_scores[key] = round(z_value, 3)
        if abs(z_value) >= 1.5:
            deviations.append(
                {
                    "metric": key,
                    "z": round(z_value, 3),
                    "mean": round(mean, 4),
                    "std": round(std, 4),
                    "value": round(value, 4),
                }
            )
    return {
        "applied": bool(z_scores),
        "baseline_used": bool(z_scores),
        "samples": (baseline or {}).get("samples", 0),
        "z": z_scores,
        "deviations": deviations,
    }

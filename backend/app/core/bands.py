"""Coarse bands for internal scores that must not be disclosed raw (trust-protocol §5.1)."""

from __future__ import annotations


def reliability_band(score: float | None) -> str:
    if score is None:
        return "no_data"
    if score >= 0.97:
        return "high"
    if score >= 0.90:
        return "medium"
    return "low"

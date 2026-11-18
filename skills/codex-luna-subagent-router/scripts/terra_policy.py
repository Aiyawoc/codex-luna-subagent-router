"""Bounded economic Terra option; never a substitute for deep Sol/Astra work."""
from __future__ import annotations

TERRA_MODEL = "gpt-6.1-terra"
TERRA_PAIR = (TERRA_MODEL, "max")


def eligible(axes):
    """Allow verifiable, bounded evidence work without widening capability floors."""
    return isinstance(axes, dict) and (
        axes.get("task_kind") in ("scan", "research", "review", "verification", "other")
        and axes.get("task_scope") == "bounded"
        and axes.get("reasoning_depth") in ("shallow", "medium")
        and axes.get("verifiability") == "yes"
        and axes.get("failure_cost") in ("low", "medium")
    )

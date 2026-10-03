"""Narrow GPT-6.1 Sol effort policy. No Host probing, network or configuration writes."""
from __future__ import annotations

SOL_MODEL = "gpt-6.1-sol"
SOL_EFFORTS = ("medium", "high", "xhigh", "max")
NEW_PAIRS = frozenset((SOL_MODEL, effort) for effort in ("medium", "max"))
EXPLICIT_ONLY_PAIRS = frozenset({(SOL_MODEL, "max")})


def medium_eligible(axes):
    """Only lower an existing Sol-tier local design decision, never upgrade Luna work.

    In the preserved static classifier, bounded architecture is the only
    verifiable medium-depth, non-high-risk workload already requiring Sol.
    Independent review is excluded by the planner before passing Host support.
    """
    return isinstance(axes, dict) and (
        axes.get("task_kind") == "architecture"
        and axes.get("task_scope") == "bounded"
        and axes.get("reasoning_depth") == "medium"
        and axes.get("verifiability") == "yes"
        and axes.get("failure_cost") in ("low", "medium")
        and axes.get("context_volume") in ("low", "medium")
    )


def automatic_pairs(supported_pairs, axes=None, *, medium_supported=False):
    """Supporting a profile never makes it an automatic retry candidate."""
    return tuple(pair for pair in supported_pairs
                 if pair not in EXPLICIT_ONLY_PAIRS
                 and (pair != (SOL_MODEL, "medium")
                      or (medium_supported is True and medium_eligible(axes))))

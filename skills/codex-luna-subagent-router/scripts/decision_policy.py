"""Typed System-1 questions used only by the optional v2.7 Shadow decision layer."""
from __future__ import annotations

QUESTIONS = {
    "task_kind": {
        "type": "choice",
        "instructions": "Classify the remaining bounded work, not quoted or already-completed work.",
        "criteria": {
            "leaf": "Small self-contained non-implementation work.",
            "scan": "Evidence collection across files, symbols, logs, or metadata.",
            "implementation": "Create or modify code or tests.",
            "debug": "Find or prove a defect cause.",
            "review": "Assess an existing change or design.",
            "architecture": "Choose cross-cutting design or compatibility boundaries.",
            "verification": "Check a concrete claim, invariant, or completed change.",
            "research": "Synthesize external or repository evidence where the answer is not already local.",
            "other": "None of the named categories fits.",
        },
    },
    "task_scope": {
        "type": "choice",
        "instructions": "Choose the remaining work scope.",
        "criteria": {
            "micro": "Tiny direct action whose startup/coordination cost dominates.",
            "bounded": "One independently ownable result with clear limits.",
            "workflow": "Multi-stage work with several dependent results.",
        },
    },
    "reasoning_depth": {
        "type": "choice",
        "instructions": "Choose the minimum reasoning depth for the remaining work.",
        "criteria": {
            "shallow": "Mechanical or directly evidenced.",
            "medium": "Several considerations but bounded ambiguity.",
            "deep": "Competing hypotheses, causal reasoning, or broad synthesis.",
        },
    },
    "verifiability": {
        "type": "choice",
        "instructions": "How directly can the result be verified with available evidence or tests?",
        "criteria": {"yes": "Directly verifiable.", "partial": "Only partly verifiable.", "no": "No reliable direct verification."},
    },
    "failure_cost": {
        "type": "choice",
        "instructions": "Classify consequence of a wrong result, independent of difficulty.",
        "criteria": {"low": "Cheap to correct.", "medium": "Meaningful rework or regression risk.", "high": "Material safety, compatibility, data, or production risk."},
    },
    "context_volume": {
        "type": "choice",
        "instructions": "Estimate how much additional context the remaining work will consume.",
        "criteria": {"low": "Small local context.", "medium": "Several files/results.", "high": "Large scan or context-isolation value."},
    },
    "evidence_scout_worthwhile": {"type": "noul", "instructions": "Would an independently owned evidence/scout result have positive net value?"},
    "parallel_siblings_likely": {"type": "noul", "instructions": "Are there at least two useful dependency-free work items that can proceed independently?"},
    "independent_analysis_worthwhile": {"type": "noul", "instructions": "Would a separate reasoning path materially reduce uncertainty or correlated error?"},
    "independent_review_worthwhile": {"type": "noul", "instructions": "Would an independent verifier/reviewer add material evidence after implementation?"},
    "context_isolation_worthwhile": {"type": "noul", "instructions": "Would isolating a large scan/research context from the Lead have positive net value?"},
    "more_evidence_required": {"type": "noul", "instructions": "Is more evidence required before a safe implementation decision?"},
    "multiple_plausible_hypotheses": {"type": "noul", "instructions": "Do at least two materially plausible explanations remain?"},
    "cross_module_causality": {"type": "noul", "instructions": "Does the remaining work require causal reasoning across module boundaries?"},
    "parallel_analysis_worthwhile": {"type": "noul", "instructions": "Would parallel independent analysis likely reduce total expected cost or elapsed time?"},
    "lead_should_continue_directly": {"type": "noul", "instructions": "Is direct Lead ownership cheaper than delegation after startup, context, and integration cost?"},
    "decision_lease": {
        "type": "choice",
        "instructions": "How long can these semantic judgments be safely reused before re-evaluation?",
        "criteria": {
            "checkpoint": "Only this decision point.",
            "evidence_phase": "Clean continuations of the current evidence phase.",
            "user_turn": "The remaining user turn is predictably stable.",
        },
    },
}

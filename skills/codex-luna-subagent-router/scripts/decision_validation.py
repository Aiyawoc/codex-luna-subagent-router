"""Pure context checks with safe JSON-pointer diagnostics, never network/key reads."""
from __future__ import annotations

import decision_state
import outcome_store as store


def issue(code, path, hint):
    return {"code": code, "path": path, "hint": hint}


def validate_context(payload, context):
    errors = []
    if not isinstance(context, dict) or set(context) - {"task_id", "state", "checkpoint"}:
        return [issue("invalid_context_shape", "/decision_context", "Use task_id, state and optional checkpoint only.")]
    tasks = payload.get("tasks") if isinstance(payload, dict) else None
    if not isinstance(tasks, list):
        return [issue("invalid_tasks", "/tasks", "Use the installed work-plan example schema.")]
    task = next((t for t in tasks if isinstance(t, dict) and t.get("task_id") == context.get("task_id")), None)
    if task is None:
        return [issue("unknown_task", "/decision_context/task_id", "Select exactly one task from tasks.")]
    axes = task.get("axes")
    if not isinstance(axes, dict) or set(axes) != set(store.AXES):
        return [issue("invalid_axes", "/tasks/*/axes", "Provide exactly the six routing axes.")]
    for name, allowed in store.AXES.items():
        if axes[name] not in allowed:
            errors.append(issue("invalid_axis_value", "/tasks/*/axes/" + name, "Allowed: " + ", ".join(allowed)))
    state = context.get("state")
    if not isinstance(state, dict):
        return errors + [issue("invalid_state", "/decision_context/state", "State must be an object.")]
    if "task_scope" in state:
        errors.append(issue("misplaced_task_scope", "/decision_context/state/task_scope",
                            "Remove this field; scope belongs in tasks[*].axes.task_scope (and optional checkpoint)."))
    if set(state) - decision_state.ALLOWED - {"task_scope"}:
        # Never reflect attacker-controlled field names or values.
        errors.append(issue("unsupported_state_fields", "/decision_context/state", "Remove fields outside decision_state.ALLOWED."))
    if errors:
        return errors
    try:
        from decision_plan import _context
        _context(payload, context)
    except (ValueError, TypeError, KeyError):
        errors.append(issue("state_or_checkpoint_mismatch", "/decision_context",
                            "Check state types/lengths, task_family, stage, hypothesis_count and checkpoint scope/module counts."))
    return errors

"""Read-only model evidence diagnostics. Configuration is not execution proof.

Optional evidence is a content-free projection supplied by an explicit caller;
it is never imported into usage/outcome ledgers or used to change routing.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import tomllib

import outcome_store as store
import runtime_support

MAX_FILE = 128 * 1024
NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:/+-]{0,127}\Z')
OLD_MODELS = re.compile(r'(?<![A-Za-z0-9_-])gpt-5\.6-(?:luna|sol)(?![A-Za-z0-9_-])')


def _text(path):
    store.safe_path(path)
    if not path.is_file():
        return None
    with path.open('rb') as handle:
        raw = handle.read(MAX_FILE+1)
    if len(raw) > MAX_FILE:
        raise ValueError('model diagnostic input exceeds budget')
    return raw.decode('utf-8')


def _name(value):
    if value is None:
        return None
    if not isinstance(value, str) or not NAME.fullmatch(value):
        raise ValueError('invalid model evidence identifier')
    return value


def compare(value):
    """Compare explicit request/Host activity/context using exact identities."""
    if (not isinstance(value, dict) or type(value.get('schema_version')) is not int or value.get('schema_version') != 1
            or set(value)-{'schema_version', 'request', 'activity', 'context', 'configured'}):
        raise ValueError('invalid model evidence schema')
    fields = {
        'request': {'call_id', 'parent_id', 'turn_id', 'model', 'effort', 'agent_type'},
        'activity': {'call_id', 'parent_id', 'turn_id', 'child_id', 'model', 'effort'},
        'context': {'child_id', 'turn_id', 'model', 'effort'},
        'configured': {'model', 'effort'},
    }
    rows = {}
    for key, allowed in fields.items():
        row = value.get(key, {})
        if not isinstance(row, dict) or set(row)-allowed:
            raise ValueError('unexpected fields in model evidence')
        rows[key] = {k: _name(v) for k, v in row.items()}
    request, activity, context = (rows[k] for k in ('request', 'activity', 'context'))
    pairs = [(request.get(k), activity.get(k)) for k in ('call_id', 'parent_id', 'turn_id')]
    pairs.append((activity.get('child_id'), context.get('child_id')))
    complete = all(a is not None and b is not None for a, b in pairs)
    chain = 'matched' if complete and all(a == b for a, b in pairs) else (
        'mismatched' if any(a is not None and b is not None and a != b for a, b in pairs) else 'unknown')
    result = 'unknown'
    if chain == 'matched' and all(row.get(k) is not None for row in (request, activity, context) for k in ('model', 'effort')):
        result = 'matched' if all(request[k] == activity[k] == context[k] for k in ('model', 'effort')) else 'mismatched'
    configured = rows['configured']
    policy = 'unknown'
    if all(row.get(k) is not None for row in (request, configured) for k in ('model', 'effort')):
        policy = 'same' if all(request[k] == configured[k] for k in ('model', 'effort')) else 'different'
    return dict(identity_chain=chain, requested_observed=result,
                current_configured_vs_historical_request=policy,
                requested={k: request.get(k) for k in ('model', 'effort')},
                observed={k: context.get(k) for k in ('model', 'effort')},
                current_configured={k: configured.get(k) for k in ('model', 'effort')},
                router_selection_provenance='unknown_without_linked_router_decision_receipt',
                source='explicit_metadata_projection', authoritative=False, routing_unchanged=True,
                warning='Current config does not reconstruct historical config. Matched names do not prove physical backend identity.')


def inventory(project_root=None, workers=None):
    home = store.codex_home()
    root = Path(project_root).resolve() if project_root else None
    layers = [('user', home)] + ([('project', root / '.codex')] if root else [])
    profiles, defaults, mentions, issues = [], [], [], []
    templates = runtime_support.ROOT / 'assets/codex-agents'
    for layer, base in layers:
        try:
            raw = _text(base / 'config.toml')
            cfg = tomllib.loads(raw) if raw is not None else {}
            defaults.append(dict(layer=layer, model=_name(cfg.get('model')),
                                 effort=_name(cfg.get('model_reasoning_effort'))))
            agents = cfg.get('agents', {})
            if not isinstance(agents, dict):
                raise ValueError('invalid role configuration')
        except (OSError, ValueError, TypeError):
            issues.append(layer+'_config_unavailable')
            agents = {}
        for template in sorted(templates.glob('*.toml')):
            role = template.stem.replace('-', '_')
            path = base / 'agents' / template.name
            explicit = agents.get(role, {})
            reference = explicit.get('config_file') if isinstance(explicit, dict) else None
            try:
                if reference is not None:
                    if not isinstance(reference, str):
                        raise ValueError('invalid profile reference')
                    path = Path(reference).expanduser()
                    if not path.is_absolute():
                        path = base / path
                raw = _text(path)
                if raw is None:
                    continue
                data = tomllib.loads(raw)
                profiles.append(dict(role=role, layer=layer,
                    model=_name(data.get('model')), effort=_name(data.get('model_reasoning_effort')),
                    matches_shipped_template=raw == template.read_text(encoding='utf-8'),
                    explicit_config_reference=reference is not None))
            except (OSError, ValueError, TypeError):
                issues.append(layer+'_'+role+'_unavailable')
    instructions = [('user', home / 'AGENTS.md')] + ([('project', root / 'AGENTS.md')] if root else [])
    for layer, path in instructions:
        try:
            raw = _text(path)
            found = sorted(set(OLD_MODELS.findall(raw or '')))
            if found:
                mentions.append(dict(layer=layer, models=found, active_policy='unknown',
                    note='A mention can be a prohibition, quotation or history. Review semantics before editing.'))
        except (OSError, ValueError, TypeError):
            issues.append(layer+'_instructions_unavailable')
    models = Counter((w.get('snapshot') or {}).get('model') or 'unknown' for w in (workers or ()))
    linked = sum(bool(w.get('receipt_id')) for w in workers) if workers is not None else None
    return dict(status='ok' if not issues else 'partial', configured_profiles=profiles,
                configured_defaults=defaults, instruction_model_mentions=mentions,
                saved_observed_models=dict(models) if workers is not None else None, workers_with_receipt_link=linked,
                workers_without_receipt_link=len(workers)-linked if workers is not None else None,
                requested_models='unknown_without_exact_request_evidence',
                runtime_profile_selection='unverified', router_selection_provenance='not_inferred',
                issues=issues, read_only=True, routing_unchanged=True,
                limitation='Disk candidates and saved usage are separate evidence, not a historical binding or effective runtime override proof.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path)
    parser.add_argument('--evidence', type=Path, help='Explicit small metadata JSON; never raw transcripts.')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    if args.evidence:
        raw = _text(args.evidence)
        if raw is None:
            raise ValueError('model evidence unavailable')
        def unique(pairs):
            data = {}
            for key, value in pairs:
                if key in data:
                    raise ValueError('duplicate evidence field')
                data[key] = value
            return data
        result = compare(json.loads(raw, object_pairs_hook=unique))
    else:
        sid, root = store.resolve_scope(args.project_root)
        import token_usage
        result = inventory(root, token_usage.statistics(scope=sid)['workers'])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, TypeError):
        print(json.dumps({'status': 'unavailable', 'reason': 'invalid_or_unavailable_model_evidence'}))
        raise SystemExit(2)

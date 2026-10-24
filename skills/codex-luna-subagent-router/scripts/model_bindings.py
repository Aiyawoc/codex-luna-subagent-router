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


# The inventory is intentionally bounded and observational, not a Host config resolver.
MAX_SCAN_FILES = 128
MAX_SCAN_BYTES = 2 * 1024 * 1024
MAX_DIRECTORY_ENTRIES = 512
MAX_CHAIN_DEPTH = 32
MAX_CONFIG_PROFILES = 32
MAX_ROLE_CANDIDATES = 128
ROLE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z')
RETIRED_MODELS = frozenset(('gpt-5.6', 'gpt-5.6-luna', 'gpt-5.6-sol',
                            'gpt-5.6-terra', 'gpt-6-sol'))
INSTRUCTION_MODELS = re.compile(
    r'(?<![A-Za-z0-9_.-])(?:gpt-5\.6(?:-(?:luna|sol|terra))?|gpt-6-sol)(?![A-Za-z0-9_-])')


class _InventoryReader:
    def __init__(self):
        self.files = 0
        self.bytes = 0
        self.entries = 0
        self.cache = {}
        self.issues = set()

    def text(self, path):
        path = Path(path).absolute()
        if path in self.cache:
            return self.cache[path]
        store.safe_path(path)
        if not path.is_file():
            return None
        if self.files >= MAX_SCAN_FILES or self.bytes >= MAX_SCAN_BYTES:
            self.issues.add('inventory_budget_exceeded')
            raise ValueError('inventory budget exceeded')
        with path.open('rb') as handle:
            raw = handle.read(min(MAX_FILE, MAX_SCAN_BYTES-self.bytes)+1)
        self.files += 1
        self.bytes += len(raw)
        if len(raw) > MAX_FILE or self.bytes > MAX_SCAN_BYTES:
            self.issues.add('inventory_budget_exceeded')
            raise ValueError('inventory input exceeds budget')
        result = raw.decode('utf-8')
        self.cache[path] = result
        return result

    def agents(self, directory):
        # Validate directory ancestors without following links or creating a sentinel.
        store.safe_path(directory / '.router-read-only-probe')
        if not directory.exists():
            return []
        paths = []
        for path in directory.iterdir():
            self.entries += 1
            if self.entries > MAX_DIRECTORY_ENTRIES:
                self.issues.add('inventory_directory_limit')
                break
            if path.suffix == '.toml':
                paths.append(path)
        return sorted(paths)


def _role(value):
    if not isinstance(value, str) or not ROLE.fullmatch(value):
        raise ValueError('invalid role or profile name')
    return value


def _source_id(path):
    import hashlib
    return hashlib.sha256(str(Path(path).absolute()).encode('utf-8')).hexdigest()[:20]


def _directories(project_root, working_directory, issues):
    root = Path(project_root).resolve() if project_root else None
    if working_directory is not None:
        current = Path(working_directory).resolve()
        if not current.is_dir():
            raise ValueError('working directory unavailable')
        if root is None:
            root = current
        if not current.is_relative_to(root):
            raise ValueError('working directory outside project root')
    elif root is not None:
        cwd = Path.cwd().resolve()
        current = cwd if cwd.is_relative_to(root) else root
    else:
        return []
    if not root.is_dir():
        raise ValueError('project root unavailable')
    parts = current.relative_to(root).parts
    if len(parts)+1 > MAX_CHAIN_DEPTH:
        issues.add('inventory_chain_limit')
    return [('project', root.joinpath(*parts[:depth]), depth)
            for depth in range(min(len(parts)+1, MAX_CHAIN_DEPTH))]


def inventory(project_root=None, workers=None, *, working_directory=None):
    reader = _InventoryReader()
    home = store.codex_home()
    directories = [('user', home, 0)] + _directories(project_root, working_directory, reader.issues)
    profiles, defaults, subdefaults, mentions, sources = [], [], [], [], []
    warnings = set()
    templates = {p.stem.replace('-', '_'): p for p in
                 (runtime_support.ROOT / 'assets/codex-agents').glob('*.toml')}
    seen = {}
    fallbacks = []

    def add_profile(path, layer, depth, *, reference=None, config_profile=None, inline=None):
        try:
            raw = reader.text(path) if inline is None else None
            if raw is None and inline is None:
                if reference is not None:
                    reader.issues.add('referenced_role_missing')
                return
            data = tomllib.loads(raw) if inline is None else inline
            declared = _role(data['name']) if 'name' in data else None
            role = declared or reference or _role(path.stem.replace('-', '_'))
            if reference and declared and reference != declared:
                warnings.add('role_name_disagreement')
            model, effort = _name(data.get('model')), _name(data.get('model_reasoning_effort'))
            if model in RETIRED_MODELS:
                warnings.add('legacy_role_model')
            key = (role, _source_id(path), config_profile, inline is not None)
            if key in seen:
                seen[key]['explicit_config_reference'] |= reference is not None
                return
            if len(profiles) >= MAX_ROLE_CANDIDATES:
                reader.issues.add('inventory_role_limit')
                return
            template = templates.get(role)
            row = dict(role=role, layer=layer, depth=depth, config_profile=config_profile,
                       model=model, effort=effort, source_id=_source_id(path),
                       source_kind='inline_role' if inline is not None else 'role_file',
                       role_source='declared_name' if declared else ('config_reference' if reference else 'filename_compatibility'),
                       matches_shipped_template=(raw == template.read_text(encoding='utf-8')) if template else None,
                       explicit_config_reference=reference is not None,
                       legacy_model=model in RETIRED_MODELS)
            profiles.append(row)
            seen[key] = row
        except (OSError, ValueError, TypeError):
            reader.issues.add('role_input_unavailable')

    def inspect_config(cfg, path, layer, depth, profile=None, selected=False):
        nonlocal fallbacks
        try:
            defaults.append(dict(layer=layer, depth=depth, config_profile=profile,
                                 selected_in_file=selected, model=_name(cfg.get('model')),
                                 effort=_name(cfg.get('model_reasoning_effort'))))
            agents = cfg.get('agents', {})
            if not isinstance(agents, dict):
                raise ValueError('invalid agents configuration')
            if any(k in agents for k in ('default_subagent_model', 'default_subagent_reasoning_effort')):
                model = _name(agents.get('default_subagent_model'))
                subdefaults.append(dict(layer=layer, depth=depth, config_profile=profile,
                    selected_in_file=selected, source_id=_source_id(path), model=model,
                    effort=_name(agents.get('default_subagent_reasoning_effort')),
                    legacy_model=model in RETIRED_MODELS))
                if model in RETIRED_MODELS:
                    warnings.add('legacy_subagent_default')
            for role, definition in agents.items():
                if not isinstance(definition, dict):
                    continue  # Scalar global agents settings are not role declarations.
                _role(role)
                reference = definition.get('config_file')
                if reference is not None:
                    if not isinstance(reference, str) or not reference or any(ord(c) < 32 for c in reference):
                        raise ValueError('invalid profile reference')
                    target = Path(reference).expanduser()
                    if not target.is_absolute():
                        target = path.parent / target
                    if target.suffix != '.toml':
                        raise ValueError('role reference must be TOML')
                    add_profile(target, layer, depth, reference=role, config_profile=profile)
                elif any(k in definition for k in ('model', 'model_reasoning_effort')):
                    add_profile(path, layer, depth, reference=role, config_profile=profile, inline=definition)
            if (profile is None or selected) and 'project_doc_fallback_filenames' in cfg:
                values = cfg['project_doc_fallback_filenames']
                if (not isinstance(values, list) or len(values) > 16 or any(
                    not isinstance(v, str) or not v or len(v) > 128 or v in ('.', '..')
                    or '/' in v or '\\' in v or ':' in v or any(ord(c) < 32 for c in v)
                    for v in values)):
                    reader.issues.add('invalid_instruction_fallback')
                else:
                    fallbacks = list(dict.fromkeys(values))
        except (OSError, ValueError, TypeError):
            reader.issues.add('config_input_unavailable')

    for layer, directory, depth in directories:
        base = directory if layer == 'user' else directory / '.codex'
        path = base / 'config.toml'
        try:
            raw = reader.text(path)
            cfg = tomllib.loads(raw) if raw is not None else {}
            inspect_config(cfg, path, layer, depth)
            named = cfg.get('profiles', {})
            if not isinstance(named, dict):
                raise ValueError('invalid named profiles')
            if len(named) > MAX_CONFIG_PROFILES:
                reader.issues.add('inventory_profile_limit')
            for index, (name, value) in enumerate(named.items()):
                if index >= MAX_CONFIG_PROFILES:
                    break
                _role(name)
                if not isinstance(value, dict):
                    raise ValueError('invalid named profile')
                inspect_config(value, path, layer, depth, profile=name, selected=name == cfg.get('profile'))
            if cfg.get('profile') is not None:
                _role(cfg['profile'])
                if cfg['profile'] not in named:
                    warnings.add('selected_config_profile_unresolved')
        except (OSError, ValueError, TypeError):
            reader.issues.add('config_input_unavailable')
        try:
            for path in reader.agents(base / 'agents'):
                add_profile(path, layer, depth)
        except (OSError, ValueError, TypeError):
            reader.issues.add('role_directory_unavailable')

    # Enumerate only the root-to-working-directory chain, never siblings or all projects.
    # Selection here is a disk-precedence candidate; Host trust, byte limits and CLI
    # overrides are not reconstructed. A mention is never classified as active policy.
    for layer, directory, depth in directories:
        selected = False
        uncertain = False
        names = ['AGENTS.override.md', 'AGENTS.md'] + (fallbacks if layer != 'user' else [])
        for name in dict.fromkeys(names):
            path = directory / name
            try:
                raw = reader.text(path)
                if raw is None:
                    continue
                candidate = None if uncertain else bool(raw) and not selected
                if raw:
                    selected = True
                kind = 'override' if name == 'AGENTS.override.md' else ('agents' if name == 'AGENTS.md' else 'fallback')
                row = dict(layer=layer, depth=depth, kind=kind, source_id=_source_id(path),
                           candidate_selected=candidate, empty=not bool(raw))
                sources.append(row)
                found = sorted(set(INSTRUCTION_MODELS.findall(raw)))
                if found:
                    warnings.add('legacy_instruction_mentions_review')
                    mentions.append(dict(row, models=found, active_policy='unknown',
                        note='Review semantics: a mention may prohibit, quote or document historical models.'))
            except (OSError, ValueError, TypeError):
                reader.issues.add('instruction_input_unavailable')
                if not selected:
                    uncertain = True

    conflicts = []
    for role in sorted({r['role'] for r in profiles}):
        rows = [r for r in profiles if r['role'] == role]
        if len(rows) > 1:
            warnings.add('multiple_role_candidates')
            conflicts.append(dict(role=role, sources=[dict(source_id=r['source_id'], layer=r['layer'],
                depth=r['depth'], config_profile=r['config_profile'], model=r['model'], effort=r['effort'])
                for r in rows], selection='unknown'))
    models = Counter((w.get('snapshot') or {}).get('model') or 'unknown' for w in (workers or ()))
    linked = sum(bool(w.get('receipt_id')) for w in workers) if workers is not None else None
    return dict(status='partial' if reader.issues else ('warning' if warnings else 'ok'),
                configured_profiles=profiles, configured_defaults=defaults,
                configured_subagent_defaults=subdefaults, role_conflicts=conflicts,
                instruction_sources=sources, instruction_model_mentions=mentions,
                saved_observed_models=dict(models) if workers is not None else None,
                workers_with_receipt_link=linked,
                workers_without_receipt_link=len(workers)-linked if workers is not None else None,
                requested_models='unknown_without_exact_request_evidence',
                runtime_profile_selection='unverified', router_selection_provenance='not_inferred',
                issues=sorted(reader.issues), warnings=sorted(warnings), read_only=True,
                authoritative=False, routing_unchanged=True,
                coverage=dict(complete=not bool(reader.issues), files_read=reader.files,
                    bytes_read=reader.bytes, directory_entries=reader.entries,
                    project_directories=sum(layer == 'project' for layer, _, _ in directories),
                    scope='user_and_root_to_working_directory_candidates',
                    host_effective_config_verified=False, host_instruction_budget_applied=False),
                limitation='Bounded disk candidates only, not historical or effective Host config. '
                           'Trust, CLI/environment overrides, plugin-provided roles and live sessions are not resolved.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path)
    parser.add_argument('--working-directory', type=Path, help='Audit only the project-root-to-directory chain.')
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
        result = inventory(root, token_usage.statistics(scope=sid)['workers'],
                           working_directory=args.working_directory or (Path.cwd() if root is None else None))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, TypeError):
        print(json.dumps({'status': 'unavailable', 'reason': 'invalid_or_unavailable_model_evidence'}))
        raise SystemExit(2)

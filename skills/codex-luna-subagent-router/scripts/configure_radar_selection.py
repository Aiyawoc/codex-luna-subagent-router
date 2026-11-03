"""Explicit IQ integration opt-in. Saves settings only, never fetches or spawns."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import configure_decision_engine as routing
import radar_selection


def configure(path, *, enabled, mode=None, confirm_data_use=False, dry_run=False, **changes):
    data = routing.read_routing(path)
    cfg = radar_selection.settings(data.get("radar_selection", {}))
    cfg["enabled"] = enabled
    if mode is not None:
        cfg["mode"] = mode
    if confirm_data_use:
        cfg["data_use_authorized"] = True
    cfg.update({k: v for k, v in changes.items() if v is not None})
    cfg = radar_selection.settings(cfg)
    if enabled and not cfg["data_use_authorized"]:
        raise ValueError("Confirm the site's data-use permission before enabling integration")
    prior = data.get("radar_selection")
    action = "unchanged" if prior == cfg else "would_update" if dry_run else "updated"
    data["radar_selection"] = cfg
    if not dry_run and action == "updated":
        routing.write_atomic(path, json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return dict(action=action, path=str(path), radar_selection=cfg, network_called=False,
                production_install_changed=False, credentials_used=False,
                note="Benchmark price is not subscription billing. Existing model/effort ceilings remain unless explicitly changed.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("user", "project"), required=True)
    parser.add_argument("--project-root")
    parser.add_argument("--codex-home", type=Path, default=routing.default_codex_home())
    parser.add_argument("--enable", action="store_true")
    parser.add_argument("--mode", choices=("observe", "select"))
    parser.add_argument("--confirm-data-use", action="store_true",
                        help="Attest permission for this integration; not a substitute for the site's authorization")
    parser.add_argument("--tier-ceiling", choices=("baseline", "luna", "sol", "astra"))
    parser.add_argument("--effort-ceiling", choices=("baseline", "low", "medium", "high", "xhigh", "max"))
    parser.add_argument("--max-benchmark-cost-ratio", type=float)
    parser.add_argument("--fetch-timeout-ms", type=int)
    parser.add_argument("--refresh-seconds", type=int)
    parser.add_argument("--max-age-hours", type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        path = routing.routing_path(args.scope, args.codex_home.expanduser().resolve(), args.project_root)
        result = configure(path, enabled=args.enable, mode=args.mode,
                           confirm_data_use=args.confirm_data_use, dry_run=args.dry_run,
                           tier_ceiling=args.tier_ceiling, effort_ceiling=args.effort_ceiling,
                           max_benchmark_cost_ratio=args.max_benchmark_cost_ratio,
                           fetch_timeout_ms=args.fetch_timeout_ms,
                           refresh_seconds=args.refresh_seconds, max_age_hours=args.max_age_hours)
    except (ValueError, OSError):
        print("ERROR: radar configuration invalid or data-use permission not confirmed", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

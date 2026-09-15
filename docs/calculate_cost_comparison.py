#!/usr/bin/env python3
"""Reprice the README's anonymous fixture. No API calls or billing integration."""
from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path

FIELDS = ('input_tokens', 'cached_input_tokens', 'output_tokens')
MILLION = Decimal(1_000_000)


def estimate(worker: dict, rates: dict) -> Decimal:
    for key in FIELDS:
        if type(worker.get(key)) is not int or worker[key] < 0:
            raise ValueError(f'{key} must be a known non-negative integer')
    if worker['cached_input_tokens'] > worker['input_tokens']:
        raise ValueError('Cached input must be a subset of input')
    if worker.get('total_tokens') != worker['input_tokens'] + worker['output_tokens']:
        raise ValueError('Total must equal input plus output')
    p = {key: Decimal(str(rates[key])) for key in ('uncached_input', 'cached_input', 'output')}
    if any(not v.is_finite() or v < 0 for v in p.values()):
        raise ValueError('Rates must be finite and non-negative')
    return ((worker['input_tokens'] - worker['cached_input_tokens']) * p['uncached_input']
            + worker['cached_input_tokens'] * p['cached_input']
            + worker['output_tokens'] * p['output']) / MILLION


def calculate(data: dict) -> dict:
    rows = []
    for worker in data['workers']:
        luna = estimate(worker, data['rates']['Luna'])
        astra = estimate(worker, data['rates']['Astra'])
        rows.append({'label': worker['label'], 'status': worker['status'],
                     'luna_usd': str(luna), 'astra_usd': str(astra),
                     'difference_usd': str(astra - luna)})
    l = sum((Decimal(r['luna_usd']) for r in rows), Decimal(0))
    a = sum((Decimal(r['astra_usd']) for r in rows), Decimal(0))
    return {'purpose': data['purpose'], 'snapshot_date': data['snapshot_date'],
            'rates': data['rates'], 'assumptions': data['assumptions'], 'workers': rows,
            'total': {'luna_usd': str(l), 'astra_usd': str(a), 'difference_usd': str(a-l),
                      'difference_percent': str((a-l) / a * 100) if a else None},
            'counts': {key: sum(w[key] for w in data['workers']) for key in ('total_tokens', *FIELDS)}}


def render_chart(result: dict, destination: Path) -> None:
    # matplotlib is an optional documentation-only dependency; not a Skill dependency.
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import StrMethodFormatter
    plt.rcParams['svg.fonttype'] = 'none'
    plt.rcParams['svg.hashsalt'] = 'codex-router-readme-cost-v1'
    values = [float(result['total']['luna_usd']), float(result['total']['astra_usd'])]
    fig, ax = plt.subplots(figsize=(10, 4.1))
    fig.subplots_adjust(left=.19, right=.87, top=.71, bottom=.29)
    bars = ax.barh(['Luna base rates', 'Astra base rates'], values, height=.46)
    ax.invert_yaxis()
    ax.set_xlim(0, max(values) * 1.16 if any(values) else 1)
    ax.set_xlabel('Illustrative cost (USD) — same token quantities', labelpad=10)
    ax.xaxis.set_major_formatter(StrMethodFormatter('${x:.0f}'))
    ax.spines[['top', 'right']].set_visible(False)
    ax.bar_label(bars, labels=[f'${v:.2f}' for v in values], padding=8, fontsize=12)
    fig.text(.05, .91, 'Same observed tokens. Different model rates.', fontsize=19, weight='bold')
    fig.text(.05, .83, f"CASE-STUDY PLACEHOLDER  |  {len(result['workers'])} Worker snapshots  |  Base-rate assumptions", fontsize=10)
    t = result['total']
    pct = f"{Decimal(t['difference_percent']):.2f}%" if t['difference_percent'] is not None else 'N/A'
    fig.text(.05, .115, f"Estimated price difference: ${Decimal(t['difference_usd']):.2f} ({pct}). Not measured savings.", fontsize=11, weight='bold')
    fig.text(.05, .047, 'Excludes Lead overhead, cache-write premiums, long-context/tier adjustments and tool fees. Rates: 2026-09-15.', fontsize=8.5)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destination, metadata={'Date': None, 'Description': result['purpose']})
    plt.close(fig)
    if destination.suffix.lower() == '.svg':
        destination.write_text('\n'.join(line.rstrip() for line in destination.read_text(encoding='utf-8').splitlines()) + '\n', encoding='utf-8')


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data', type=Path, default=Path(__file__).parent/'examples/cost-comparison.json')
    p.add_argument('--svg', type=Path, help='Optional chart output (requires matplotlib)')
    args = p.parse_args()
    try:
        result = calculate(json.loads(args.data.read_text(encoding='utf-8')))
        if args.svg:
            render_chart(result, args.svg)
    except (OSError, ValueError, TypeError, KeyError, ImportError) as exc:
        p.exit(2, f'Cannot build documentation example: {exc}\n')
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()

"""Immutable, synthetic two-product example with explicit human review."""
import copy
import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path


def new_example():
    return {'run_id': uuid.uuid4().hex, 'parent_run_id': None, 'year': 2024,
            'region_code': '110108', 'mode': 'synthetic_training', 'status': 'waiting_input',
            'gep_total': None, 'items': {
                'maize': {'status': 'example_only', 'quantity_t': 2935.1,
                          'quantity_source': '2025 Haidian yearbook table 5-11, printed page 71',
                          'price_yuan_t': 2000, 'output_yuan': 5870200,
                          'intermediate_yuan': 2000000, 'labor_yuan': 1200000,
                          'depreciation_yuan': 400000, 'net_tax_yuan': 100000,
                          'capital_return_yuan': 300000, 'residual_yuan': 1870200,
                          'warning': 'Only quantity is sourced; all prices/costs are synthetic, not Haidian GEP.'},
                'fish': {'status': 'waiting_input', 'quantity_t': None,
                         'source': '2025 Haidian yearbook table 5-5, printed page 67: blank',
                         'missing': ['harvest quantity', 'producer price', 'inputs/capital costs'],
                         'allowed_methods': ['manual', 'area_yield', 'stock_survival', 'defer']}}, 'audit': []}


def _number(payload, key, maximum=None):
    value = payload[key]
    if isinstance(value, bool):
        raise ValueError(f'{key}: boolean is not a measurement')
    n = float(value)
    if not math.isfinite(n) or n < 0 or (maximum is not None and n > maximum):
        raise ValueError(f'{key}: outside allowed range')
    return n


def _child(run, action, actor):
    r = copy.deepcopy(run)
    r['parent_run_id'], r['run_id'] = run['run_id'], uuid.uuid4().hex
    r['audit'].append({'action': action, 'actor': actor,
                       'time_utc': datetime.now(timezone.utc).isoformat()})
    return r


def resolve(run, item, payload):
    if run.get('mode') != 'synthetic_training' or item != 'fish':
        raise ValueError('This prototype handles the synthetic fish quantity example only')
    if not str(payload.get('operator', '')).strip() or not str(payload.get('evidence', '')).strip():
        raise ValueError('operator and evidence are required')
    method = payload.get('method')
    if method == 'manual':
        q = _number(payload, 'quantity_t')
    elif method == 'area_yield':
        q = _number(payload, 'area_ha') * _number(payload, 'yield_t_ha')
    elif method == 'stock_survival':
        q = (_number(payload, 'stock_count') * _number(payload, 'survival', 1)
             * _number(payload, 'weight_kg') * _number(payload, 'harvest_fraction', 1) / 1000)
    elif method == 'defer':
        q = None
    else:
        raise ValueError('unknown method')
    if q is not None and not math.isfinite(q):
        raise ValueError('non-finite estimate')
    r = _child(run, f'resolve:{item}', payload['operator'])
    r['items'][item].pop('reviewer', None)
    r['items'][item].update(quantity_t=q, proposal=copy.deepcopy(payload),
                            status='waiting_input' if method == 'defer' else 'pending_review')
    r['status'] = r['items'][item]['status']
    r['gep_total'] = None
    return r


def approve(run, item, reviewer):
    if not reviewer.strip() or run['items'][item]['status'] != 'pending_review':
        raise ValueError('a named reviewer and pending proposal are required')
    if reviewer == run['items'][item]['proposal']['operator']:
        raise ValueError('reviewer must differ from input operator')
    r = _child(run, f'approve_quantity:{item}', reviewer)
    r['items'][item]['status'] = 'approved'
    r['items'][item]['reviewer'] = reviewer
    r['status'] = 'waiting_valuation_inputs'
    r['gep_total'] = None
    return r


def save(run, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as f:
        json.dump(run, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n')

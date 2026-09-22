"""Validate the reviewed yearbook extraction without turning blanks into zero."""
import csv
import hashlib
import math
from pathlib import Path

from .admission import INDICATOR_IDS, admit

FIELDS = {'region_code', 'year', 'table_id', 'printed_page', 'pdf_page',
          'source_file', 'metric', 'value', 'unit', 'status', 'notes'}
STATUSES = {'observed', 'blank_unresolved', 'scope_conflict'}


def check(path):
    errors, seen, count, pending = [], set(), 0, 0
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        if set(reader.fieldnames or []) != FIELDS:
            return {'valid': False, 'errors': ['CSV schema mismatch'], 'row_count': 0, 'pending_count': 0}
        for line, row in enumerate(reader, 2):
            count += 1
            reasons = []
            if None in row or any(v is None for v in row.values()):
                errors.append(f'line {line}: malformed CSV row')
                continue
            key = tuple(row[k] for k in ('region_code', 'year', 'table_id', 'metric'))
            if key in seen:
                reasons.append('duplicate primary key')
            seen.add(key)
            if row['year'] != '2024' or row['region_code'] != '110108':
                reasons.append('outside the declared region/year')
            if row['status'] not in STATUSES:
                reasons.append('unknown status')
            if row['status'] != 'observed':
                pending += 1
            if row['status'] == 'blank_unresolved' and row['value'].strip():
                reasons.append('unresolved blank has a value')
            if row['status'] != 'blank_unresolved' or row['value'].strip():
                try:
                    if not math.isfinite(float(row['value'])):
                        raise ValueError()
                except ValueError:
                    reasons.append('numeric value must be finite')
            for k in ('table_id', 'metric', 'unit', 'source_file'):
                if not row[k].strip():
                    reasons.append(f'missing {k}')
            for k in ('printed_page', 'pdf_page'):
                if not row[k].isdigit() or int(row[k]) < 1:
                    reasons.append(f'invalid {k}')
            src = Path(row['source_file'])
            if src.is_absolute() or '..' in src.parts:
                reasons.append('source path must be local-relative')
            errors.extend(f'line {line}: {r}' for r in reasons)
    if count == 0:
        errors.append('empty table')
    return {'valid': not errors, 'errors': errors, 'row_count': count, 'pending_count': pending,
            'scope': 'schema and consistency check; observation means transcribed, not accounting-ready'}


def build(path):
    report = check(path)
    if not report['valid']:
        raise ValueError('; '.join(report['errors']))
    result = {'schema_version': 1, 'region_code': '110108', 'year': 2024,
              'scope': 'reference_only', 'accounting_ready': False,
              'observations': [], 'pending': [], 'check': report,
              'source_sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest()}
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        for line, row in enumerate(csv.DictReader(f), 2):
            row['row_id'] = hashlib.sha256('|'.join(row[k] for k in ('region_code', 'year', 'table_id', 'metric')).encode()).hexdigest()[:16]
            row['csv_line'] = line
            row['value'] = float(row['value']) if row['value'].strip() else None
            row['source_distribution'] = 'local_original_only; follow official source link'
            result['observations' if row['status'] == 'observed' else 'pending'].append(row)
    return result


def build_reference_admission(path):
    """Import yearbook rows into an explicitly unreviewed admission manifest.

    The source CSV is read only.  Its observations are useful evidence, but
    they cannot become accounting inputs until a person approves the source,
    units, applicability and the method-specific required fields.
    """
    catalog = build(path)
    source_hash = catalog["source_sha256"]
    records = []
    for row in catalog["observations"] + catalog["pending"]:
        records.append({
            "node_id": f"reference.{row['row_id']}",
            "indicator_id": "reference",
            "region_code": row["region_code"],
            "year": row["year"],
            "source_id": "haidian_yearbook_2025",
            "value": row["value"],
            "unit": row["unit"],
            "raw_status": row["status"],
            "status": "pending_review",
            "sha256": source_hash,
            "product_id": "",
            "table_id": row["table_id"],
            "printed_page": row["printed_page"],
            "metric": row["metric"],
            "source_file": row["source_file"],
        })
    return admit(records, {indicator_id: "pending" for indicator_id in INDICATOR_IDS}, {}, [])

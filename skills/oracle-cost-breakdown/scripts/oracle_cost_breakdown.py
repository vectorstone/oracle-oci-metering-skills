#!/usr/bin/env python3
from __future__ import annotations

import argparse
import configparser
import csv
import gzip
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from decimal import Decimal


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description='Aggregate OCI cost report composition by month, service, and description.')
    p.add_argument('--start-month', required=True)
    p.add_argument('--end-month', required=True)
    p.add_argument('--csv', required=True)
    p.add_argument('--summary-md', required=True)
    p.add_argument('--profile', default=os.environ.get('OCI_CLI_PROFILE', 'DEFAULT'))
    p.add_argument('--oci-bin', default=os.environ.get('OCI_CLI_BIN', ''))
    p.add_argument('--workers', type=int, default=16)
    p.add_argument('--window-padding-days', type=int, default=2)
    p.add_argument('--top-n', type=int, default=10)
    return p.parse_args(argv)


def month_start(s: str) -> datetime:
    return datetime.strptime(s, '%Y-%m').replace(tzinfo=timezone.utc)


def month_after(dt: datetime) -> datetime:
    if dt.month == 12:
        return dt.replace(year=dt.year + 1, month=1)
    return dt.replace(month=dt.month + 1)


def resolve_oci_bin(cli: str) -> str:
    if cli:
        return cli
    for cand in (shutil.which('oci'), str(pathlib.Path.home() / 'bin' / 'oci')):
        if cand and os.path.exists(cand):
            return cand
    raise SystemExit('Could not find OCI CLI. Pass --oci-bin or fix PATH.')


def read_ctx(profile: str, cli: str) -> tuple[str, str, str]:
    cfg = configparser.ConfigParser()
    path = os.path.expanduser('~/.oci/config')
    if not cfg.read(path):
        raise SystemExit('~/.oci/config not found')
    if profile not in cfg:
        raise SystemExit(f'OCI profile {profile!r} not found')
    sec = cfg[profile]
    tenancy = sec.get('tenancy', '').strip()
    region = sec.get('region', '').strip()
    if not tenancy or not region:
        raise SystemExit('tenancy or region missing in config')
    return resolve_oci_bin(cli), tenancy, region


def list_cost_objects(oci_bin: str, tenancy: str, region: str, profile: str) -> list[dict]:
    cmd = [oci_bin, 'os', 'object', 'list', '--region', region, '--namespace-name', 'bling', '--bucket-name', tenancy, '--prefix', 'reports/cost-csv/', '--all', '--output', 'json']
    if profile != 'DEFAULT':
        cmd[1:1] = ['--profile', profile]
    return json.loads(subprocess.check_output(cmd, text=True)).get('data', [])


def select_objects(items: list[dict], start: datetime, end_exclusive: datetime, padding_days: int) -> list[tuple[datetime, str]]:
    create_start = start - timedelta(days=padding_days)
    create_end = end_exclusive + timedelta(days=padding_days)
    out = []
    for it in items:
        tc = it.get('time-created')
        if not tc:
            continue
        dt = datetime.fromisoformat(tc.replace('Z', '+00:00'))
        if create_start <= dt < create_end:
            out.append((dt, it['name']))
    out.sort()
    return out


def download(oci_bin: str, tenancy: str, region: str, profile: str, selected: list[tuple[datetime, str]], workers: int) -> list[pathlib.Path]:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix='oci-cost-breakdown-'))

    def dl(name: str) -> pathlib.Path:
        out = tmp / pathlib.Path(name).name
        cmd = [oci_bin, 'os', 'object', 'get', '--region', region, '--namespace-name', 'bling', '--bucket-name', tenancy, '--name', name, '--file', str(out)]
        if profile != 'DEFAULT':
            cmd[1:1] = ['--profile', profile]
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return out

    files: list[pathlib.Path] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(dl, name) for _, name in selected]
        for fut in as_completed(futs):
            files.append(fut.result())
    return files


def aggregate(files: list[pathlib.Path], start: datetime, end_exclusive: datetime) -> tuple[list[tuple[str, str, str, Decimal, Decimal]], dict[str, Decimal], dict[str, Decimal]]:
    rows: dict[tuple[str, str, str], dict[str, Decimal]] = defaultdict(lambda: {'my_cost': Decimal('0'), 'billed_quantity': Decimal('0')})
    month_cost: dict[str, Decimal] = defaultdict(lambda: Decimal('0'))
    month_billed: dict[str, Decimal] = defaultdict(lambda: Decimal('0'))
    for path in files:
        with gzip.open(path, 'rt', newline='') as f:
            r = csv.DictReader(f)
            for row in r:
                try:
                    dt = datetime.strptime(row['lineItem/intervalUsageStart'], '%Y-%m-%dT%H:%MZ').replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                if not (start <= dt < end_exclusive):
                    continue
                month = dt.strftime('%Y-%m')
                service = row.get('product/service', '')
                desc = row.get('product/Description', '')
                my_cost = Decimal(row.get('cost/myCost', '0') or '0')
                billed = Decimal(row.get('usage/billedQuantity', '0') or '0')
                key = (month, service, desc)
                rows[key]['my_cost'] += my_cost
                rows[key]['billed_quantity'] += billed
                month_cost[month] += my_cost
                month_billed[month] += billed
    data = []
    for (month, service, desc), agg in sorted(rows.items()):
        data.append((month, service, desc, agg['my_cost'], agg['billed_quantity']))
    return data, dict(month_cost), dict(month_billed)


def write_outputs(data, month_cost, month_billed, csv_path: pathlib.Path, summary_path: pathlib.Path, top_n: int) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['month', 'service', 'description', 'my_cost', 'billed_quantity'])
        for month, service, desc, my_cost, billed in sorted(data):
            w.writerow([month, service, desc, f'{my_cost}', f'{billed}'])

    lines = ['# Oracle 月度成本/用量成分简报', '', '## 月度概览', '']
    for month in sorted(month_cost):
        lines.append(f'- {month}：myCost={month_cost[month]}，billedQuantity={month_billed.get(month, Decimal("0"))}')
    lines += ['', '## Top 项（按 myCost，其次 billedQuantity）', '']
    ranked = sorted(data, key=lambda x: (x[3], x[4]), reverse=True)[:top_n]
    for month, service, desc, my_cost, billed in ranked:
        lines.append(f'- {month} | {service} | {desc} | myCost={my_cost} | billedQuantity={billed}')
    summary_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    start = month_start(args.start_month)
    end_inclusive = month_start(args.end_month)
    end_exclusive = month_after(end_inclusive)
    if end_exclusive <= start:
        raise SystemExit('--end-month must be >= --start-month')
    oci_bin, tenancy, region = read_ctx(args.profile, args.oci_bin)
    items = list_cost_objects(oci_bin, tenancy, region, args.profile)
    selected = select_objects(items, start, end_exclusive, args.window_padding_days)
    files = download(oci_bin, tenancy, region, args.profile, selected, args.workers)
    data, month_cost, month_billed = aggregate(files, start, end_exclusive)
    write_outputs(data, month_cost, month_billed, pathlib.Path(args.csv), pathlib.Path(args.summary_md), args.top_n)
    print(f'Wrote CSV to {args.csv}')
    print(f'Wrote summary to {args.summary_md}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))

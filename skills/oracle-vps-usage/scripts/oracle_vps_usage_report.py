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
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from decimal import Decimal


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description='Aggregate OCI VPS outbound traffic by month from Oracle usage reports.')
    p.add_argument('--start-month', required=True, help='Start month, inclusive, in YYYY-MM')
    p.add_argument('--end-month', required=True, help='End month, inclusive, in YYYY-MM')
    p.add_argument('--csv', required=True, help='Output CSV path')
    p.add_argument('--summary-md', required=True, help='Output markdown summary path')
    p.add_argument('--profile', default=os.environ.get('OCI_CLI_PROFILE', 'DEFAULT'))
    p.add_argument('--oci-bin', default=os.environ.get('OCI_CLI_BIN', ''))
    p.add_argument('--workers', type=int, default=16)
    p.add_argument('--window-padding-days', type=int, default=2)
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


@dataclass
class OciContext:
    oci_bin: str
    tenancy: str
    region: str
    profile: str


def read_ctx(args: argparse.Namespace) -> OciContext:
    cfg = configparser.ConfigParser()
    path = os.path.expanduser('~/.oci/config')
    if not cfg.read(path):
        raise SystemExit('~/.oci/config not found')
    if args.profile not in cfg:
        raise SystemExit(f'OCI profile {args.profile!r} not found in ~/.oci/config')
    sec = cfg[args.profile]
    tenancy = sec.get('tenancy', '').strip()
    region = sec.get('region', '').strip()
    if not tenancy or not region:
        raise SystemExit('tenancy or region missing in ~/.oci/config')
    return OciContext(resolve_oci_bin(args.oci_bin), tenancy, region, args.profile)


def run_json(cmd: list[str]) -> dict:
    return json.loads(subprocess.check_output(cmd, text=True))


def list_usage_objects(ctx: OciContext) -> list[dict]:
    cmd = [ctx.oci_bin, 'os', 'object', 'list', '--region', ctx.region, '--namespace-name', 'bling', '--bucket-name', ctx.tenancy, '--prefix', 'reports/usage-csv/', '--all', '--output', 'json']
    if ctx.profile != 'DEFAULT':
        cmd[1:1] = ['--profile', ctx.profile]
    return run_json(cmd).get('data', [])


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


def download_candidates(ctx: OciContext, selected: list[tuple[datetime, str]], workers: int) -> list[pathlib.Path]:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix='oci-vps-usage-'))

    def dl(name: str) -> pathlib.Path:
        out = tmp / pathlib.Path(name).name
        cmd = [ctx.oci_bin, 'os', 'object', 'get', '--region', ctx.region, '--namespace-name', 'bling', '--bucket-name', ctx.tenancy, '--name', name, '--file', str(out)]
        if ctx.profile != 'DEFAULT':
            cmd[1:1] = ['--profile', ctx.profile]
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return out

    files: list[pathlib.Path] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(dl, name) for _, name in selected]
        for fut in as_completed(futs):
            files.append(fut.result())
    return files


def aggregate(files: list[pathlib.Path], start: datetime, end_exclusive: datetime) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
    month_totals: dict[str, Decimal] = defaultdict(lambda: Decimal('0'))
    resource_totals: dict[str, Decimal] = defaultdict(lambda: Decimal('0'))
    for path in files:
        with gzip.open(path, 'rt', newline='') as f:
            r = csv.DictReader(f)
            for row in r:
                if row.get('product/service') != 'NETWORK':
                    continue
                if row.get('usage/consumedQuantityUnits') != 'BYTES':
                    continue
                if row.get('usage/consumedQuantityMeasure') != 'DATA_TRANSFERRED':
                    continue
                try:
                    dt = datetime.strptime(row['lineItem/intervalUsageStart'], '%Y-%m-%dT%H:%MZ').replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                if not (start <= dt < end_exclusive):
                    continue
                qty = Decimal(row.get('usage/consumedQuantity', '0'))
                month_totals[dt.strftime('%Y-%m')] += qty
                resource_totals[row.get('product/resourceId', '')] += qty
    return dict(month_totals), dict(resource_totals)


def write_outputs(month_totals: dict[str, Decimal], resource_totals: dict[str, Decimal], csv_path: pathlib.Path, summary_path: pathlib.Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    total = sum(month_totals.values(), Decimal('0'))
    with csv_path.open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['month', 'bytes', 'gb_10', 'gib_2'])
        for month in sorted(month_totals):
            qty = month_totals[month]
            w.writerow([month, f'{qty}', f'{qty / (Decimal(10) ** 9)}', f'{qty / (Decimal(1024) ** 3)}'])
        w.writerow(['TOTAL', f'{total}', f'{total / (Decimal(10) ** 9)}', f'{total / (Decimal(1024) ** 3)}'])

    top_resource = max(resource_totals.items(), key=lambda kv: kv[1])[0] if resource_totals else ''
    lines = [
        '# Oracle VPS 月度流量简报',
        '',
        '- 统计口径：`NETWORK / BYTES / DATA_TRANSFERRED`',
        f'- 主要资源：`{top_resource}`' if top_resource else '- 主要资源：未识别',
        '',
        '## 月度流量',
        '',
    ]
    for month in sorted(month_totals):
        qty = month_totals[month]
        lines.append(f'- {month}：{qty:,} Bytes ≈ {qty / (Decimal(10) ** 9):.3f} GB ≈ {qty / (Decimal(1024) ** 3):.3f} GiB')
    lines += [
        '',
        '## 合计',
        '',
        f'- {total:,} Bytes',
        f'- ≈ {total / (Decimal(10) ** 9):.3f} GB',
        f'- ≈ {total / (Decimal(1024) ** 3):.3f} GiB',
        '',
        '## 说明',
        '',
        '- 统计基于 Oracle 托管 usage-csv 报表。',
        '- 月份归属以 CSV 行中的 `lineItem/intervalUsageStart` 为准。',
        '- 为避免漏算月末小时流量，候选对象下载窗口会在请求月份前后各扩 2 天。',
    ]
    summary_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    start = month_start(args.start_month)
    end_inclusive = month_start(args.end_month)
    end_exclusive = month_after(end_inclusive)
    if end_exclusive <= start:
        raise SystemExit('--end-month must be >= --start-month')
    ctx = read_ctx(args)
    items = list_usage_objects(ctx)
    selected = select_objects(items, start, end_exclusive, args.window_padding_days)
    files = download_candidates(ctx, selected, args.workers)
    month_totals, resource_totals = aggregate(files, start, end_exclusive)
    write_outputs(month_totals, resource_totals, pathlib.Path(args.csv), pathlib.Path(args.summary_md))
    print(f'Wrote CSV to {args.csv}')
    print(f'Wrote summary to {args.summary_md}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))

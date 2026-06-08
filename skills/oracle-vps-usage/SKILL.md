---
name: oracle-vps-usage
description: Use when the user wants monthly Oracle Cloud Infrastructure VPS traffic statistics from Oracle-managed usage reports, especially outbound traffic for compute instances or VNICs, and wants CSV output plus a readable monthly brief. Trigger for OCI VPS traffic, Oracle usage report, usage-csv, monthly bandwidth, egress traffic, or VNIC traffic analysis.
---

# Oracle VPS Usage

Use this skill to compute OCI VPS traffic from Oracle-managed usage reports.

It is intentionally narrow:

- reads Oracle-managed `reports/usage-csv/` objects from namespace `bling`
- uses the tenancy OCID as the bucket name
- filters real VPS traffic with:
  - `product/service = NETWORK`
  - `usage/consumedQuantityUnits = BYTES`
  - `usage/consumedQuantityMeasure = DATA_TRANSFERRED`
- aggregates by calendar month using `lineItem/intervalUsageStart`

## Use this skill when

- the user asks how much traffic an Oracle VPS used
- the user wants the last N months of bandwidth usage
- the user already configured OCI CLI auth and wants a deterministic script
- the user wants a CSV plus a short report

## Important pitfalls

1. Do **not** rely on object creation month alone. Month-end usage rows may be stored in objects created in the next month.
2. Do **not** sum `OBJECTSTORE` rows for VPS traffic. They can include zero-byte or log-related transfer rows with similar resource names.
3. `reports/usage-csv/` uses flat filenames, so you usually need to list objects and then filter by object creation time and row interval time.
4. The report bucket is Oracle-managed. Use the tenancy home region, namespace `bling`, bucket name = tenancy OCID.

## Quick start

```bash
python ~/.codex/skills/oracle-vps-usage/scripts/oracle_vps_usage_report.py           --start-month 2026-03           --end-month 2026-05           --csv ./oracle-vps-traffic.csv           --summary-md ./oracle-vps-traffic-brief.md
```

## Workflow

1. Resolve OCI CLI binary and config profile.
2. List Oracle-managed `usage-csv` objects.
3. Expand the object creation window by ±2 days around the requested months.
4. Download candidate objects.
5. Parse CSV rows and trust `lineItem/intervalUsageStart` as the month boundary.
6. Keep only `NETWORK / BYTES / DATA_TRANSFERRED` rows.
7. Write CSV and markdown summary.

## Resources

- Script: `scripts/oracle_vps_usage_report.py`
- Notes: `references/report-notes.md`

Read the notes when the numbers look suspicious or when month boundaries do not reconcile with the object timestamps.

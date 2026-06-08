---
name: oracle-cost-breakdown
description: Use when the user wants Oracle Cloud Infrastructure cost composition or billed-quantity breakdown from Oracle-managed cost reports, grouped by month, service, and description, and wants CSV plus a markdown summary. Trigger for OCI cost report, cost-csv, cost composition, service breakdown, or monthly bill analysis.
---

# Oracle Cost Breakdown

Use this skill to summarize OCI cost reports from Oracle-managed `reports/cost-csv/` objects.

## Use this skill when

- the user wants a cost composition table by month
- the user wants billed quantity by service or description
- the user wants to inspect free-tier vs paid usage patterns
- the user already has OCI CLI auth configured

## Scope

This skill reads `reports/cost-csv/` and aggregates:

- `cost/myCost`
- `usage/billedQuantity`
- `product/service`
- `product/Description`

## Quick start

```bash
python ~/.codex/skills/oracle-cost-breakdown/scripts/oracle_cost_breakdown.py           --start-month 2026-05           --end-month 2026-05           --csv ./oracle-cost-breakdown-2026-05.csv           --summary-md ./oracle-cost-breakdown-2026-05.md
```

## Important pitfalls

1. `reports/cost-csv/` uses flat filenames too, so month selection should not assume a month prefix exists.
2. Cost can be zero while usage is real, especially under free tier.
3. For traffic-only questions, `usage-csv` is more precise than `cost-csv`.

## Resources

- Script: `scripts/oracle_cost_breakdown.py`
- Notes: `references/report-notes.md`

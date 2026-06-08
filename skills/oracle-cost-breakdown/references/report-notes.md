# Oracle cost report notes

Key facts:

- cost report namespace: `bling`
- bucket name: tenancy OCID
- region: tenancy home region
- report prefix: `reports/cost-csv/`
- monthly grouping should use `lineItem/intervalUsageStart`

Common traps:

- free-tier resources can show real billed quantity but zero `cost/myCost`
- `reports/cost-csv/` is not month-foldered in the old report layout
- for pure traffic statistics, `usage-csv` is the better source

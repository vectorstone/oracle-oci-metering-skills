# Oracle OCI Metering Skills

Reusable Codex skills and scripts for Oracle Cloud Infrastructure metering analysis.

Included skills:

- `oracle-vps-usage`: query Oracle-managed `usage-csv` reports and aggregate VPS outbound traffic by month.
- `oracle-cost-breakdown`: query Oracle-managed `cost-csv` reports and aggregate billed quantity / cost composition by month and service.

These skills assume:

- OCI CLI is installed and authenticated.
- The active profile in `~/.oci/config` contains `tenancy` and `region`.
- Oracle-managed reports are accessible from the tenancy home region via namespace `bling` and bucket name = tenancy OCID.

Example:

```bash
python skills/oracle-vps-usage/scripts/oracle_vps_usage_report.py           --start-month 2026-03           --end-month 2026-05           --csv ./examples/oracle-vps-traffic-sample.csv           --summary-md ./examples/oracle-vps-traffic-sample-brief.md
```

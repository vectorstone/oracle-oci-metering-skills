# Oracle VPS usage report notes

Key facts:

- report namespace: `bling`
- bucket name: tenancy OCID
- region: tenancy home region
- authoritative monthly boundary: `lineItem/intervalUsageStart`
- authoritative traffic rows: `NETWORK / BYTES / DATA_TRANSFERRED`

Common traps:

- Filtering only on object `time-created` can undercount month-end hours.
- `oci os object list --start ...` is lexicographic, not date-aware.
- `OBJECTSTORE` rows with `PIC_COMPUTE_OUTBOUND_DATA_TRANSFER_ZONE1` are not the same as the VPS network total.

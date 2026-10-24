# Synthetic Demo Data

Both shipment files contain **160 fictional input rows**, including deliberately
invalid records. They are generated locally with seed 42 by `src/demo.py`.
They contain no customer records, no real company performance and no purchased data.
Carrier names beginning with `Demo` are fictional.

- `synthetic_shipments.csv`: UTF-8, comma-separated table.
- `synthetic_shipments.xlsx`: the same table in the first sheet (`Shipments`),
  with provenance and editing instructions on `Read me`.
- Reference analysis date: **2026-10-01**, inclusive UTC day.
- Cost currency: **USD** throughout. Costs and transit times are invented inputs,
  not market rates or carrier promises.

Routes connect China, Europe, the United States and Southeast Asia. Cases include
on-time/early delivery, completed delay, overdue/in-transit shipments, four high-cost
records, missing values, invalid dates/costs, chronology conflicts and a duplicate ID.

Regenerate from the project root:

```bash
python -m src.demo
```

This intentionally overwrites the two named synthetic example files. It never
reads, changes or saves user-uploaded data. Tests contain separate hand-calculated
cases so they do not rely only on this generator's output.

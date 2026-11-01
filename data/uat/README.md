# Synthetic UAT data

These hand-authored fixtures are **Synthetic Demo Data**, not customer or carrier records.
Recreate with `python -m scripts.uat_fixtures`; analysis date UTC **2026-10-01**.

Both CSVs contain 120 unique orders, eight fictional carriers with exactly15 each,
60 Air /60 Sea, valid USD100 costs and ISO UTC timestamps.

- `synthetic_uat_120.csv`: active IDs1–7 and21–50 (37), completed late IDs8–20 and51–63 (26),
  other57 delivered on time. Exactly63 exception orders; zero V1 field-quality findings.
  All37 active orders lack optional V2 evidence, so no complete score or high-priority conclusion.
  The first20 exceptions reproduce the reported page counts7 /0 /7 /13.
- `synthetic_uat_120_active.csv`: all120 in transit and overdue, for50-row active paging.
  Expected pages: IDs1–50,51–100,101–120. No optional V2 evidence is invented.

A single order may have multiple exception reasons or quality findings. Counts of source rows,
unique shipments, exception orders, active orders and field-quality findings are different units.

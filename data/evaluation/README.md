# Independent synthetic reference cases

`reference_cases.json` is a manually authored, versioned fixture, not a model output.
`base_shipment` supplies common fictional V1 fields, and each case overrides them.
The fixed analysis date is 2026-10-01, inclusive UTC day.

Four cases have explicit ordinal preferences and written business rationales:
immediate deadline with declared dependencies/exposure, next-shift handling,
valuable cargo with slack and explicitly zero exposure, then routine monitoring.
Five further cases specify expected handling of missing inputs, invalid context,
normal shipments, completed shipments and unidentified rows.

Reference ranks are never computed from or passed into a ranking formula. The
runtime scorer ignores them; evaluation reads them only after computing V2 outputs.
Tests verify this separation and a stress profile that changes the order.

This small teaching fixture is not statistically representative, expert-labelled,
held-out production data or evidence of prediction accuracy. It exercises intended
behaviour and makes policy/assumption sensitivity visible.

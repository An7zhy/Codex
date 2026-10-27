# Public transport input-contract fixture

Source: https://github.com/plotly/datasets
Commit: `0c447c47b757ad74edecab31f0d72f849d2e67c2`
Original path: `2011_february_us_airport_traffic.csv`

The full CSV (221 airport aggregate rows) and the repository's MIT LICENSE were
read from that public Git commit. The adjacent provenance.json records its hash.

Important: the upstream README lists this sample's original source as **Unknown**.
This fixture is a legally published transport visualization sample, not verified
shipment transactions or carrier delivery/SLA ground truth. We use it only to
test the real file's native schema against the product's shipment template. It
must not be enriched with invented costs/delivery dates and called real business
validation. All other hand-authored audit contract probes are explicitly synthetic.

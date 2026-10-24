"""Downloads with protection against spreadsheet formula interpretation."""

import pandas as pd


def csv_bytes(frame: pd.DataFrame) -> bytes:
    """Export UTF-8 BOM CSV, prefixing formula-like text with an apostrophe.

    Numeric values stay numeric. Original raw strings remain available in the app;
    formula-like strings are escaped only in downloaded CSVs for safe Excel opening.
    """
    safe = frame.copy()
    for column in safe.select_dtypes(include=["object", "string"]).columns:
        safe[column] = safe[column].map(
            lambda value: "'" + value
            if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@"))
            else value
        )
    return safe.to_csv(index=False, date_format="%Y-%m-%dT%H:%M:%SZ").encode("utf-8-sig")

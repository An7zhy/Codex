"""Read tabular inputs without saving user uploads on disk."""

from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile

import pandas as pd

from src.schema import DataInputError, REQUIRED_COLUMNS

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_ROWS = 100_000


def validate_columns(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame.columns = [str(column).strip().lower() for column in frame.columns]
    if frame.columns.duplicated().any():
        raise DataInputError("Column names must be unique after trimming and lowercasing.")
    missing = sorted(set(REQUIRED_COLUMNS) - set(frame.columns))
    if missing:
        raise DataInputError("Missing required columns: " + ", ".join(missing))
    return frame


def load_shipments(content: bytes, filename: str) -> pd.DataFrame:
    """Load UTF-8 CSV or the first Excel worksheet; preserve IDs as text."""
    if not content or not content.strip():
        raise DataInputError("The file is empty. Upload a table with the required headers.")
    if len(content) > MAX_FILE_BYTES:
        raise DataInputError("The file exceeds the 20 MB limit.")
    suffix = Path(filename).suffix.lower()
    try:
        if suffix == ".csv":
            frame = pd.read_csv(
                BytesIO(content), encoding="utf-8-sig", dtype=str,
                keep_default_na=False, nrows=MAX_ROWS + 1,
            )
        elif suffix == ".xlsx":
            frame = pd.read_excel(
                BytesIO(content), engine="openpyxl", sheet_name=0, dtype=str,
                keep_default_na=False, nrows=MAX_ROWS + 1,
            )
        else:
            raise DataInputError("Choose an .xlsx or UTF-8 .csv file.")
    except DataInputError:
        raise
    except (pd.errors.EmptyDataError, pd.errors.ParserError, UnicodeError,
            ValueError, BadZipFile, OSError, KeyError) as exc:
        raise DataInputError(
            "The file could not be read. Use a comma-separated UTF-8 CSV or a valid "
            ".xlsx workbook with shipment headers on the first row of the first sheet."
        ) from exc
    if len(frame) > MAX_ROWS:
        raise DataInputError("Use at most 100,000 input rows for this local MVP.")
    return validate_columns(frame)

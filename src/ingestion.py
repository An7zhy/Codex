"""Read tabular inputs without saving user uploads on disk."""

import csv
from io import BytesIO, TextIOWrapper
from pathlib import Path
from zipfile import BadZipFile
from openpyxl.utils.exceptions import InvalidFileException

import pandas as pd

from src.schema import DataInputError, REQUIRED_COLUMNS

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_ROWS = 100_000
# Match the file-size guard rather than csv's much smaller default cell limit.
csv.field_size_limit(MAX_FILE_BYTES)


def _validate_named_headers(columns) -> None:
    """Inspect raw names before pandas can hide duplicates as column.1."""
    names = [str(column).strip().lower() for column in columns if column is not None and str(column).strip()]
    if len(names) != len(set(names)):
        raise DataInputError("Column names must be unique after trimming and lowercasing.")


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
            with TextIOWrapper(BytesIO(content), encoding="utf-8-sig", newline="") as stream:
                reader = csv.reader(stream, strict=True)
                header = next((row for row in reader if any(cell.strip() for cell in row)), [])
                _validate_named_headers(header)
                records = 0
                for row in reader:
                    if not row or (len(row) == 1 and not row[0].strip()):
                        continue
                    records += 1
                    if records > MAX_ROWS:
                        raise DataInputError("Use at most 100,000 input rows for this local MVP.")
                    if len(row) > len(header):
                        raise DataInputError(
                            f"CSV record {records + 1} has {len(row)} fields but the header has {len(header)}. "
                            "Remove extra separators or correct CSV quoting; columns cannot be aligned safely."
                        )
            frame = pd.read_csv(
                BytesIO(content), encoding="utf-8-sig", dtype=str,
                keep_default_na=False, nrows=MAX_ROWS + 1,
            )
        elif suffix == ".xlsx":
            with pd.ExcelFile(BytesIO(content), engine="openpyxl") as workbook:
                if not workbook.book.worksheets:
                    raise DataInputError("The workbook has no tabular worksheets.")
                header = next(workbook.book.worksheets[0].iter_rows(min_row=1, max_row=1, values_only=True), ())
                _validate_named_headers(header)
                frame = pd.read_excel(workbook, sheet_name=0, dtype=str,
                                      keep_default_na=False, nrows=MAX_ROWS + 1)
        else:
            raise DataInputError("Choose an .xlsx or UTF-8 .csv file.")
    except DataInputError:
        raise
    except (pd.errors.EmptyDataError, pd.errors.ParserError, UnicodeError,
            ValueError, BadZipFile, OSError, KeyError, csv.Error, SyntaxError, InvalidFileException) as exc:
        raise DataInputError(
            "The file could not be read. Use a comma-separated UTF-8 CSV or a valid "
            ".xlsx workbook with shipment headers on the first row of the first sheet."
        ) from exc
    if len(frame) > MAX_ROWS:
        raise DataInputError("Use at most 100,000 input rows for this local MVP.")
    return validate_columns(frame)

"""CSV output that is safe to open in Excel.

A cell starting with = + - @ (or a tab / carriage return) can run as a formula when the file is
opened in a spreadsheet ("CSV injection"). Such text cells are prefixed with an apostrophe.
Plain numbers such as -1409.00 are left alone so amounts stay numeric.
"""

import csv
import io
import re
from collections.abc import Iterable

FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
PLAIN_NUMBER = re.compile(r"^[+-]?\d+(\.\d+)?$")


def safe_cell(value: object) -> object:
    if not isinstance(value, str) or not value:
        return value
    if value.startswith(FORMULA_START) and not PLAIN_NUMBER.match(value):
        return "'" + value
    return value


def csv_text(header: list[str], rows: Iterable[Iterable[object]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([safe_cell(cell) for cell in header])
    for row in rows:
        writer.writerow([safe_cell(cell) for cell in row])
    return buffer.getvalue()

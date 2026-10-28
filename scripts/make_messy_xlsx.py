"""Build data/messy.xlsx, a small deliberately messy workbook for testing.

Sheet "Sales":   title row, blank row, then headers on row 3. One header is
                 empty and its column has no values.
Sheet "Targets": clean table keyed by EmployeeId, so it joins to
                 chinook.employees (Sales Support Agents are 3, 4, 5).

Usage: python scripts/make_messy_xlsx.py [output_path]
"""

import sys
from datetime import date
from pathlib import Path

from openpyxl import Workbook

SALES_ROWS = [
    ("North", 12500.50, 120, date(2026, 7, 3)),
    ("South", 9800.00, 95, date(2026, 7, 10)),
    ("East", 15320.75, 143, date(2026, 7, 17)),
    ("West", 7650.25, 70, date(2026, 7, 24)),
    ("North", 13100.00, 128, date(2026, 8, 7)),
    ("South", 10250.40, 101, date(2026, 8, 14)),
    ("East", 14980.10, 139, date(2026, 8, 21)),
    ("West", 8120.90, 76, date(2026, 8, 28)),
    ("North", 12890.00, 125, date(2026, 9, 4)),
    ("South", 9990.60, 98, date(2026, 9, 11)),
    ("East", 16010.00, 150, date(2026, 9, 18)),
    ("West", 7980.30, 73, date(2026, 9, 25)),
]

TARGET_ROWS = [
    (3, "Jane Peacock", "Q3", 40000),
    (4, "Margaret Park", "Q3", 38000),
    (5, "Steve Johnson", "Q3", 35000),
    (3, "Jane Peacock", "Q4", 42000),
    (4, "Margaret Park", "Q4", 39500),
    (5, "Steve Johnson", "Q4", 36000),
]


def build(out_path: Path) -> None:
    wb = Workbook()

    sales = wb.active
    assert sales is not None  # a new Workbook always has one sheet
    sales.title = "Sales"
    sales.append(["Q3 Sales Report"])  # title row above the headers
    sales.append([])  # blank row
    sales.append(["Region", None, "Revenue", "Units", "Date"])  # empty header
    for region, revenue, units, day in SALES_ROWS:
        sales.append([region, None, revenue, units, day])  # empty column

    targets = wb.create_sheet("Targets")
    targets.append(["EmployeeId", "Employee Name", "Quarter", "Target"])
    for row in TARGET_ROWS:
        targets.append(list(row))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/messy.xlsx")
    build(out)
    print(f"Wrote {out}")

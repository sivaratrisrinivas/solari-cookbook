"""Night-shift production tickets trapped in a shop-floor Calc workbook."""

from __future__ import annotations

from pathlib import Path

# Mixed good and dirty rows on purpose. The normalizer is the point.
TICKETS_CSV = """ticket_id,line,sku,lot,qty,unit,status,operator,closed_at
TKT-104221,3,SKU-BRZ12,LOT-9F2A,12.50,kg,closed,m.chen,2026-09-07
TKT-104222,7,SKU-ALM04,LOT-1C88,40,ea,closed,j.okonkwo,2026-09-07
TKT-104223,1,SKU-PVC08,LOT-44B1,-3,kg,closed,r.patel,2026-09-07
TKT-104224,12,SKU-BRZ12,LOT-9F2A,8,kg,maybe,m.chen,2026-09-07
TKT-104225,4,SKU-NIT02,LOT-77D0,2.00,L,hold,a.singh,2026-09-07
TKT-104226,not-a-line,SKU-ALM04,LOT-1C88,1,ea,closed,j.okonkwo,2026-09-07
"""

APP_ROOT = Path(__file__).resolve().parents[1]


def fixtures_dir() -> Path:
    packaged = Path(__file__).resolve().parent / "fixtures"
    checkout = APP_ROOT / "fixtures"
    if checkout.exists():
        return checkout
    return packaged


def tickets_csv_path() -> Path:
    return fixtures_dir() / "night-shift-tickets.csv"


def tickets_ods_path() -> Path:
    return fixtures_dir() / "night-shift-tickets.ods"

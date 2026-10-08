"""Parse NCE "Market Total" report text into structured sale data."""
import re
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO


@dataclass
class GradeRow:
    grade: str
    bags: int
    weight_kg: int
    min_price: float
    max_price: float
    value_usd: float
    avg_price: float  # USD per 50 kg


@dataclass
class Sale:
    sale_no: int
    sale_date: str  # ISO yyyy-mm-dd
    grades: list[GradeRow] = field(default_factory=list)
    total_avg_price: float | None = None


_HEADER = re.compile(r"Sale\s+(\d+)\s+of\s+\w+,\s+(\w+\s+\d{1,2},\s+\d{4})", re.I)
_ROW = re.compile(
    r"^([A-Z][A-Z0-9]*)\s+([\d,]+)\s+([\d,]+)\s+([\d,.]+)\s+([\d,.]+)\s+([\d,.]+)\s+([\d,.]+)\s*$"
)
_TOTAL = re.compile(r"^TOTAL:?\s+[\d,]+\s+[\d,]+\s+[\d,.]+\s+[\d,.]+\s+[\d,.]+\s+([\d,.]+)\s*$")


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def parse_text(text: str) -> Sale:
    m = _HEADER.search(text)
    if not m:
        raise ValueError("Could not find 'Sale N of <date>' header")
    sale_date = datetime.strptime(m.group(2), "%B %d, %Y").date().isoformat()
    sale = Sale(sale_no=int(m.group(1)), sale_date=sale_date)
    for line in text.splitlines():
        line = line.strip()
        t = _TOTAL.match(line)
        if t:
            sale.total_avg_price = _num(t.group(1))
            continue
        r = _ROW.match(line)
        if r:
            sale.grades.append(
                GradeRow(
                    grade=r.group(1),
                    bags=int(_num(r.group(2))),
                    weight_kg=int(_num(r.group(3))),
                    min_price=_num(r.group(4)),
                    max_price=_num(r.group(5)),
                    value_usd=_num(r.group(6)),
                    avg_price=_num(r.group(7)),
                )
            )
    if not sale.grades:
        raise ValueError("No grade rows found in report")
    return sale


def parse_pdf(data: bytes) -> Sale:
    import pdfplumber

    with pdfplumber.open(BytesIO(data)) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)
    return parse_text(text)

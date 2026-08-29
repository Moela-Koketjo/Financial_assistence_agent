"""Generate a synthetic multi-page FNB-style statement PDF for testing and demos.

Every merchant, amount, and account number here is invented. Use this instead of
a real statement so genuine financial data never reaches the Gemini API.

    python samples/generate_statement.py

By default writes samples/sample_statement.pdf (3 pages, 60 transactions, Feb 2026).
Use --month/--year/--seed/--out to generate other periods.
"""

import argparse
import calendar
import random
from pathlib import Path

PAGE_W, PAGE_H = 595, 842          # A4 in PDF points
FONT_SIZE = 8
LINE_HEIGHT = 11
LEFT_MARGIN = 32
TOP_Y = PAGE_H - 50
ROWS_PER_PAGE = 22

OUT_PATH = Path(__file__).parent / "sample_statement.pdf"

# (description, min, max, is_credit) — merchants chosen to exercise every
# categorisation path: keyword hits, credits, and unknowns for the review queue
MERCHANTS = [
    ("POS PURCHASE CHECKERS HYPER RANDBURG", 120, 890, False),
    ("POS PURCHASE PNP FAMILY NORTHGATE", 95, 640, False),
    ("POS PURCHASE WOOLWORTHS FOOD SANDTON", 180, 720, False),
    ("POS PURCHASE SHOPRITE MONTANA", 85, 410, False),
    ("POS PURCHASE SPAR SUPERSPAR LYNNWOOD", 110, 530, False),
    ("POS PURCHASE CLICKS STORE 4471", 60, 380, False),
    ("PREPAID AIRTIME MTN", 29, 149, False),
    ("PREPAID AIRTIME VODACOM", 29, 199, False),
    ("OTT VOUCHER PURCHASE", 50, 250, False),
    ("TELKOM MOBILE DATA BUNDLE", 99, 349, False),
    ("POS PURCHASE KFC MENLYN", 45, 220, False),
    ("POS PURCHASE STEERS BROOKLYN", 60, 260, False),
    ("POS PURCHASE NANDOS HATFIELD", 85, 310, False),
    ("UBEREATS ORDER", 90, 420, False),
    ("MR D FOOD DELIVERY", 75, 330, False),
    ("BOLT TRIP JOHANNESBURG", 38, 190, False),
    ("UBER TRIP PRETORIA", 45, 240, False),
    ("MONTHLY ACCOUNT FEE", 69, 69, False),
    ("CASH WITHDRAWAL CHARGE", 12, 38, False),
    ("PREPAID ELECTRICITY TSHWANE", 150, 700, False),
    ("MUNICIPAL WATER PAYMENT", 210, 640, False),
    ("SEND MONEY TO MMA", 200, 1500, False),
    ("EFT PAYMENT TO T MOKOENA", 150, 900, False),
    ("TAKEALOT ONLINE ORDER", 199, 1450, False),
    # deliberately unfamiliar — these fall through to the LLM and land in review
    ("POS PURCHASE CAFE ROSSI 0021", 48, 180, False),
    ("DEBIT ORDER DISCOVERY LIFE", 380, 480, False),
    ("POS PURCHASE THE LOCAL BREW CO", 55, 165, False),
    ("ONLINE PMT REF INV-2291", 250, 980, False),
    ("POS PURCHASE ENGEN GARAGE N1", 300, 950, False),
    ("DEBIT ORDER PLANET FITNESS", 399, 399, False),
    ("POS PURCHASE DISCHEM PHARMACY", 90, 470, False),
    ("SALARY DEPOSIT ACME LOGISTICS", 18500, 18500, True),
    ("REFUND TAKEALOT ORDER", 199, 650, True),
]


DEBITS = MERCHANTS[:-2]
SALARY = MERCHANTS[-2]
REFUND = MERCHANTS[-1]


def _rows(rng: random.Random, month: int, year: int, count: int, opening: float) -> list[tuple]:
    """Build `count` dated transaction rows with a running balance."""
    month_abbr = calendar.month_abbr[month]
    last_day = calendar.monthrange(year, month)[1]
    rows: list[tuple] = []
    balance = opening
    day = 1
    salary_paid = False
    for i in range(count):
        if day >= 25 and not salary_paid:
            desc, lo, hi, credit = SALARY
            salary_paid = True
        elif rng.random() < 0.05:
            desc, lo, hi, credit = REFUND
        else:
            desc, lo, hi, credit = rng.choice(DEBITS)
        amount = round(rng.uniform(lo, hi), 2)
        fee = 0.00 if credit else rng.choice([0.00, 0.00, 0.00, 1.50, 2.25, 4.50])
        balance = balance + amount if credit else balance - amount - fee
        rows.append((f"{day:02d} {month_abbr} {year}", desc, fee, amount, credit, round(balance, 2)))
        if i % 2 == 1 and day < last_day:
            day += 1
    return rows


def _page_lines(rows: list[tuple], page_no: int, page_count: int, month: int, year: int) -> list[str]:
    """Render one page of the statement as fixed-width text lines."""
    head = [
        "FIRST NATIONAL BANK",
        "Next Transact Account",
        "",
        "Account Holder : A SAMPLE",
        "Account Number : 6200000000000",
        f"Statement Period: 01 {calendar.month_name[month]} {year} to "
        f"{calendar.monthrange(year, month)[1]} {calendar.month_name[month]} {year}",
        f"Page {page_no} of {page_count}",
        "",
        f"{'Date':<12}{'Description':<40}{'Fee':>8}{'Amount':>13}{'Balance':>14}",
        "-" * 87,
    ]
    body = [
        f"{d:<12}{desc[:39]:<40}{(f'{fee:.2f}' if fee else ''):>8}"
        f"{f'{amt:,.2f}' + ('Cr' if cr else '  '):>13}{bal:>14,.2f}"
        for d, desc, fee, amt, cr, bal in rows
    ]
    return head + body


def _escape(text: str) -> str:
    """Escape characters that are special inside a PDF string literal."""
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _content_stream(lines: list[str]) -> bytes:
    """Build a PDF content stream that draws the given lines in Courier."""
    out = [f"BT /F1 {FONT_SIZE} Tf {LEFT_MARGIN} {TOP_Y} Td {LINE_HEIGHT} TL"]
    out += [f"({_escape(line)}) Tj T*" for line in lines]
    out.append("ET")
    return "\n".join(out).encode("latin-1", "replace")


def build_pdf(pages: list[list[str]]) -> bytes:
    """Assemble text pages into a minimal, valid PDF file."""
    objects: dict[int, bytes] = {}
    page_ids = [4 + 2 * i for i in range(len(pages))]

    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode()
    objects[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>"

    for i, lines in enumerate(pages):
        pid, cid = page_ids[i], page_ids[i] + 1
        objects[pid] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {cid} 0 R >>"
        ).encode()
        stream = _content_stream(lines)
        objects[cid] = b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream)

    body, offsets = bytearray(b"%PDF-1.4\n"), {}
    for num in sorted(objects):
        offsets[num] = len(body)
        body += b"%d 0 obj\n%s\nendobj\n" % (num, objects[num])

    xref_at, count = len(body), max(objects) + 1
    body += b"xref\n0 %d\n0000000000 65535 f \n" % count
    for num in range(1, count):
        body += b"%010d 00000 n \n" % offsets.get(num, 0)
    body += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (count, xref_at)
    return bytes(body)


def main() -> None:
    """Generate a synthetic statement PDF from command-line options."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--month", type=int, default=2, help="statement month, 1-12")
    ap.add_argument("--year", type=int, default=2026, help="statement year")
    ap.add_argument("--count", type=int, default=60, help="number of transactions")
    ap.add_argument("--opening", type=float, default=24000.0, help="opening balance")
    ap.add_argument("--seed", type=int, default=20260227, help="RNG seed — same seed, same file")
    ap.add_argument("--out", type=Path, default=OUT_PATH, help="output PDF path")
    args = ap.parse_args()

    rows = _rows(random.Random(args.seed), args.month, args.year, args.count, args.opening)
    chunks = [rows[i:i + ROWS_PER_PAGE] for i in range(0, len(rows), ROWS_PER_PAGE)]
    pages = [
        _page_lines(c, i + 1, len(chunks), args.month, args.year)
        for i, c in enumerate(chunks)
    ]
    args.out.write_bytes(build_pdf(pages))
    print(
        f"Wrote {args.out} — {len(pages)} pages, {len(rows)} transactions, "
        f"{args.month:02d}/{args.year}"
    )


if __name__ == "__main__":
    main()

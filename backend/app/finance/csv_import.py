"""Read spending from a bank's CSV export. Most US banks let you download one for free.

Banks name their columns differently, so we look for the usual names:
- date: "Date", "Transaction Date", "Posted Date", ...
- what: "Description", "Merchant", "Name", "Payee", ...
- money: one signed "Amount" column (negative = money out), or separate "Debit"/"Credit" columns,
  or an "Amount" plus a "Type" column saying debit/credit.
Only money going out is spending. Money coming in is skipped: Kharcha tracks income separately.
"""

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime

MAX_ROWS = 5000

DATE_COLS = ("date", "transaction date", "posted date", "posting date", "trans date", "trans. date")
TEXT_COLS = ("description", "merchant", "name", "payee", "details", "memo", "transaction description")
AMOUNT_COLS = ("amount", "transaction amount", "amount (usd)")
DEBIT_COLS = ("debit", "debits", "withdrawal", "withdrawals", "money out", "debit amount")
CREDIT_COLS = ("credit", "credits", "deposit", "deposits", "money in", "credit amount")
TYPE_COLS = ("type", "transaction type", "credit/debit", "debit/credit")
DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%b %d, %Y", "%d %b %Y", "%Y/%m/%d")


@dataclass(frozen=True)
class SpendRow:
    on: date
    merchant: str
    amount: float  # positive: money spent


@dataclass
class ParseResult:
    rows: list[SpendRow]
    skipped_income: int = 0
    skipped_bad: int = 0


class CsvError(ValueError):
    pass


def _find(headers: dict[str, str], names: tuple[str, ...]) -> str | None:
    for n in names:
        if n in headers:
            return headers[n]
    return None


def parse_money(raw: str | None) -> float | None:
    if raw is None:
        return None
    s = raw.strip().replace("$", "").replace(",", "").replace("USD", "").strip()
    if not s:
        return None
    negative = s.startswith("(") and s.endswith(")")
    s = s.strip("()").strip()
    if s.endswith("-"):  # some banks write 12.50-
        negative, s = True, s[:-1]
    try:
        value = float(s)
    except ValueError:
        return None
    return -abs(value) if negative else value


def parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    s = raw.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_bank_csv(data: bytes) -> ParseResult:
    text = data.decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise CsvError("The file has no header row.")
    headers = {h.strip().lower(): h for h in reader.fieldnames if h}
    date_col = _find(headers, DATE_COLS)
    text_col = _find(headers, TEXT_COLS)
    amount_col = _find(headers, AMOUNT_COLS)
    debit_col = _find(headers, DEBIT_COLS)
    credit_col = _find(headers, CREDIT_COLS)
    type_col = _find(headers, TYPE_COLS)
    if not date_col or not text_col or not (amount_col or debit_col):
        raise CsvError("Couldn't find the date, description and amount columns. "
                       "Expected headers like Date, Description and Amount (or Debit/Credit).")

    out = ParseResult(rows=[])
    for i, row in enumerate(reader):
        if i >= MAX_ROWS:
            break
        on = parse_date(row.get(date_col))
        merchant = (row.get(text_col) or "").strip()
        if on is None or not merchant:
            out.skipped_bad += 1
            continue
        spent: float | None = None
        if debit_col:
            debit = parse_money(row.get(debit_col))
            credit = parse_money(row.get(credit_col)) if credit_col else None
            if debit:
                spent = abs(debit)
            elif credit:
                out.skipped_income += 1
                continue
        if spent is None and amount_col:
            amount = parse_money(row.get(amount_col))
            if amount is None:
                out.skipped_bad += 1
                continue
            kind = (row.get(type_col) or "").strip().lower() if type_col else ""
            if kind:
                is_out = any(w in kind for w in ("debit", "withdraw", "purchase", "payment", "sale"))
            else:
                is_out = amount < 0  # signed amounts: negative means money out
            if not is_out or amount == 0:
                out.skipped_income += 1
                continue
            spent = abs(amount)
        if not spent:
            out.skipped_bad += 1
            continue
        out.rows.append(SpendRow(on, merchant[:120], round(spent, 2)))
    return out

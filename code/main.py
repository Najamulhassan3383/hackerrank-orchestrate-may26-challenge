"""Read tickets, call Bedrock, save the raw reply, and write the answer sheet."""

import argparse
import csv
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from bedrock_client import complete
from embed import embed_text
from parse import parse_answer
from prompt import SYSTEM_PROMPT, ticket_message, user_prompt
from retrieve import search

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ROOT / "support_tickets" / "sample_support_tickets.csv"
OUTPUT_CSV = ROOT / "support_tickets" / "output.csv"
RAW_DIR = ROOT / "runs" / "raw"

SHEET_COLUMNS = (
    "issue",
    "subject",
    "company",
    "response",
    "product_area",
    "status",
    "request_type",
    "justification",
)


def _field(row: dict[str, str], name: str) -> str:
    wanted = name.lower()
    for key, value in row.items():
        if key and key.lower() == wanted:
            return (value or "").strip()
    return ""


def read_tickets(path: Path, limit: int) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        tickets = []
        for row in reader:
            tickets.append(
                {
                    "issue": _field(row, "issue"),
                    "subject": _field(row, "subject"),
                    "company": _field(row, "company"),
                }
            )
            if len(tickets) >= limit:
                break
    return tickets


def write_sheet(rows: list[dict[str, str]]) -> None:
    with OUTPUT_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SHEET_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def run(input_path: Path, limit: int) -> None:
    load_dotenv(ROOT / ".env")
    tickets = read_tickets(input_path, limit)
    if not tickets:
        raise RuntimeError(f"No tickets in {input_path}")

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, ticket in enumerate(tickets, start=1):
        query = ticket_message(**ticket)
        hits = search(embed_text(query), company=ticket["company"])
        print("  " + " | ".join(hit.path for hit in hits), flush=True)
        raw = complete(SYSTEM_PROMPT, user_prompt(**ticket, documents=[hit.body for hit in hits]))
        raw_path = RAW_DIR / f"{index:04d}.txt"
        raw_path.write_text(raw, encoding="utf-8", newline="\n")

        try:
            answer = parse_answer(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            answer = {
                "status": "",
                "product_area": "",
                "response": "",
                "request_type": "",
                "justification": f"Parse error: {exc}",
            }

        rows.append({**ticket, **answer})
        print(f"ticket {index}/{len(tickets)} saved {raw_path.name}")

    write_sheet(rows)
    print(f"wrote {len(rows)} row(s) to {OUTPUT_CSV}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Send tickets to Bedrock and fill the answer sheet.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Ticket CSV to read")
    parser.add_argument("--limit", type=int, default=1, help="How many rows to send")
    args = parser.parse_args()
    if args.limit < 1:
        raise SystemExit("--limit must be at least 1")
    try:
        run(args.input, args.limit)
    except Exception as exc:
        print(f"pipeline failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()

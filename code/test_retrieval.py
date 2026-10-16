"""Check chunking rules, then check that questions retrieve the expected articles.

A case passes when one of its expected files appears in the top search results.
"""

import sys
from pathlib import Path

from dotenv import load_dotenv

from chunking import MAX_CHARS, chunk_article, is_release_notes
from embed import embed_text
from retrieve import TOP_K, search

ROOT = Path(__file__).resolve().parent.parent

CASES = (
    {
        "name": "test expiration",
        "company": "HackerRank",
        "question": "How long do assigned tests stay active if no end date is set?",
        "paths": (
            "data/hackerrank/screen/managing-tests/2979262079-modify-test-expiration-time.md",
            "data/hackerrank/screen/test-settings/9672590042-modifying-general-settings-for-tests.md",
        ),
    },
    {
        "name": "test variants",
        "company": "HackerRank",
        "question": "When should I create a variant of a test instead of a new test?",
        "paths": ("data/hackerrank/screen/managing-tests/7530103378-test-variants.md",),
    },
    {
        "name": "extra time",
        "company": "HackerRank",
        "question": "How do I reinvite a candidate and add extra time accommodation?",
        "paths": ("data/hackerrank/screen/managing-tests/4811403281-adding-extra-time-for-candidates.md",),
    },
    {
        "name": "delete account",
        "company": "HackerRank",
        "question": "I signed up with Google and have no password. How do I delete my HackerRank account?",
        "paths": (
            "data/hackerrank/hackerrank_community/account-settings/manage-account/5618101592-delete-an-account.md",
            "data/hackerrank/hackerrank_community/account-settings/manage-account/1917106962-manage-account-faqs.md",
        ),
    },
    {
        "name": "delete conversation",
        "company": "Claude",
        "question": "How do I delete a Claude conversation that has private information?",
        "paths": ("data/claude/claude/conversation-management/8230524-how-can-i-delete-or-rename-a-conversation.md",),
    },
    {
        "name": "stolen cheques",
        "company": "Visa",
        "question": "My Visa traveller's cheques were stolen. What number do I call?",
        "paths": ("data/visa/support/consumer/travelers-cheques.md",),
    },
    {
        "name": "lost card",
        "company": "Visa",
        "question": "Where can I report a lost or stolen Visa card from India?",
        "paths": ("data/visa/support.md",),
    },
)


def check_chunking() -> list[str]:
    failures = []
    short = chunk_article(ROOT / "data" / "visa" / "note.md", "# Hello\n\nShort article.")
    if len(short) != 1:
        failures.append(f"short article produced {len(short)} chunks")

    heading = "## Section\n\n" + ("word " * 2000)
    body = "# Title\n\nIntro.\n\n" + heading
    if len(body) <= MAX_CHARS:
        failures.append("fixture was not long enough to split")
    pieces = chunk_article(ROOT / "data" / "visa" / "note.md", body)
    if len(pieces) < 2:
        failures.append(f"long article produced {len(pieces)} chunks")

    notes = ROOT / "data" / "hackerrank" / "general-help" / "release-notes" / "notes.md"
    if not is_release_notes(notes):
        failures.append("release notes were not skipped")
    return failures


def unique_paths(hits) -> list[str]:
    seen = []
    for hit in hits:
        if hit.path not in seen:
            seen.append(hit.path)
    return seen


def check_search() -> tuple[int, int]:
    passed = 0
    for case in CASES:
        hits = search(embed_text(case["question"]), company=case["company"], limit=TOP_K)
        found = unique_paths(hits)
        ok = any(path in found for path in case["paths"])
        passed += int(ok)
        label = "PASS" if ok else "FAIL"
        print(f"{label} {case['name']}")
        print(f"  expected: {', '.join(case['paths'])}")
        if not hits:
            print("  retrieved: none")
            continue
        for hit in hits:
            print(f"  {hit.distance:.3f}  {hit.path}")
    return passed, len(CASES)


def main() -> None:
    load_dotenv(ROOT / ".env")
    print("chunking")
    failures = check_chunking()
    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
    else:
        print("PASS short article stays whole, long article splits, release notes are skipped")

    print("\nretrieval")
    passed, total = check_search()
    print(f"\n{passed}/{total} questions retrieved an expected document")
    if failures or passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"tests failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

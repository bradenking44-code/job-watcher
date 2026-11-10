import gzip
import json

from job_watcher.history import read_history, rebuild_history, title_matches


def _snapshot(root, day, success, postings):
    folder = root / day
    folder.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_date": day,
        "source_id": "sample",
        "source_name": "Sample Co.",
        "ats": "Workday",
        "success": success,
        "postings": postings,
    }
    with gzip.open(folder / "sample.json.gz", "wt", encoding="utf-8") as handle:
        json.dump(payload, handle)


def _posting(posting_id, title, location="Tulsa, OK"):
    return {
        "posting_id": posting_id,
        "external_id": posting_id.split(":", 1)[-1],
        "title": title,
        "location": location,
        "department": "Finance",
        "posted_date": "2026-11-09",
        "url": "https://example.test/job",
    }


def test_history_ignores_failed_source_runs_and_marks_removals_on_next_success(tmp_path):
    raw = tmp_path / "raw"
    output = tmp_path / "history.csv"
    config = {
        "markets": {"tulsa_ok": {"cities": ["Tulsa"]}, "northwest_ar": {"cities": ["Bentonville"]}},
        "finance_title_terms": ["finance", "accountant", "audit"],
    }
    _snapshot(raw, "2026-11-09", True, [_posting("sample:A", "Finance Intern"), _posting("sample:B", "Software Engineer")])
    _snapshot(raw, "2026-11-10", False, [])

    rows = rebuild_history(raw, output, config)
    by_id = {row["posting_id"]: row for row in rows}
    assert by_id["sample:A"]["status"] == "open"
    assert by_id["sample:A"]["last_seen"] == "2026-11-09"

    _snapshot(raw, "2026-11-11", True, [_posting("sample:B", "Software Engineer"), _posting("sample:C", "Staff Accountant")])
    rows = rebuild_history(raw, output, config)
    by_id = {row["posting_id"]: row for row in rows}

    assert by_id["sample:A"]["status"] == "removed"
    assert by_id["sample:A"]["removed_date"] == "2026-11-11"
    assert by_id["sample:B"]["status"] == "open"
    assert by_id["sample:C"]["in_role"] == "true"
    assert by_id["sample:C"]["market"] == "tulsa_ok"
    assert read_history(output) == rows


def test_title_matching_uses_word_boundaries():
    assert title_matches("Senior Financial Analyst", ["financial"])
    assert title_matches("Revenue Auditor", ["audit"])
    assert not title_matches("Texas Field Representative", ["tax"])


def test_reappearing_posting_keeps_first_seen_and_clears_removed_date(tmp_path):
    raw = tmp_path / "raw"
    output = tmp_path / "history.csv"
    config = {
        "markets": {"tulsa_ok": {"cities": ["Tulsa"]}},
        "finance_title_terms": ["finance", "accountant"],
    }
    posting = _posting("sample:A", "Finance Analyst")
    _snapshot(raw, "2026-11-09", True, [posting])
    _snapshot(raw, "2026-11-10", True, [])

    removed = rebuild_history(raw, output, config)[0]
    assert removed["first_seen"] == "2026-11-09"
    assert removed["last_seen"] == "2026-11-09"
    assert removed["status"] == "removed"
    assert removed["removed_date"] == "2026-11-10"

    _snapshot(raw, "2026-11-11", True, [posting])
    reopened = rebuild_history(raw, output, config)[0]
    assert reopened["first_seen"] == "2026-11-09"
    assert reopened["last_seen"] == "2026-11-11"
    assert reopened["status"] == "open"
    assert reopened["removed_date"] == ""

    first_build = output.read_bytes()
    rebuild_history(raw, output, config)
    assert output.read_bytes() == first_build

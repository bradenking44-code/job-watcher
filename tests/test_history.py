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


def test_history_keeps_only_target_market_jobs_and_localizes_multi_location_rows(tmp_path):
    raw = tmp_path / "raw"
    output = tmp_path / "history.csv"
    config = {
        "markets": {"tulsa_ok": {"cities": ["Tulsa"]}},
        "finance_title_terms": ["finance"],
    }
    local = _posting("sample:local", "Finance Analyst", "Tulsa, OK; Houston, TX; Denver, CO")
    outside = _posting("sample:outside", "Finance Analyst", "Little Rock, AR")
    _snapshot(raw, "2026-11-09", True, [local, outside])

    rows = rebuild_history(raw, output, config)

    assert [row["posting_id"] for row in rows] == ["sample:local"]
    assert rows[0]["location"] == "Tulsa, OK"
    assert rows[0]["market"] == "tulsa_ok"
    assert rows[0]["in_market"] == "true"


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


def test_retired_source_history_is_separate_from_required_open_removed_statuses(tmp_path):
    raw = tmp_path / "raw"
    output = tmp_path / "history.csv"
    archive_raw = tmp_path / "archive" / "raw"
    config = {
        "markets": {"tulsa_ok": {"cities": ["Tulsa"]}},
        "finance_title_terms": ["finance"],
        "inactive_source_ids": ["bok_financial"],
    }
    _snapshot(raw, "2026-11-11", True, [_posting("sample:A", "Finance Analyst")])
    bok_posting = {
        **_posting("bok_financial:1198061800", "Finance Associate"),
        "external_id": "1198061800",
        "employer": "BOK Financial",
    }
    for day in ("2026-11-10", "2026-11-11"):
        folder = archive_raw / day
        folder.mkdir(parents=True, exist_ok=True)
        snapshot = {
            "run_date": day,
            "source_id": "bok_financial",
            "source_name": "BOK Financial",
            "ats": "SAP SuccessFactors Recruiting Marketing",
            "employer": "BOK Financial",
            "success": True,
            "postings": [bok_posting],
        }
        with gzip.open(folder / "bok_financial.json.gz", "wt", encoding="utf-8") as handle:
            json.dump(snapshot, handle)

    rows = rebuild_history(raw, output, config)
    archived_rows = read_history(tmp_path / "archive" / "history.csv")

    assert [row["posting_id"] for row in rows] == ["sample:A"]
    assert {row["status"] for row in rows} <= {"open", "removed"}
    assert len(archived_rows) == 1
    assert archived_rows[0]["posting_id"] == "bok_financial:1198061800"
    assert archived_rows[0]["status"] == "archived"
    assert archived_rows[0]["removed_date"] == ""

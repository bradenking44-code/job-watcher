import gzip
import json
from datetime import date

from job_watcher.pipeline import run_pipeline
from job_watcher.sources import SourceFetchError


def _posting(source_id, external_id, title):
    return {
        "posting_id": f"{source_id}:{external_id}",
        "external_id": external_id,
        "title": title,
        "location": "Tulsa, OK",
        "department": "Finance",
        "posted_date": "2026-11-09",
        "url": f"https://example.test/{external_id}",
    }


def test_pipeline_records_failures_without_raw_files_and_reruns_replace_the_day(tmp_path, monkeypatch):
    root = tmp_path
    config_path = root / "sources.json"
    config = {
        "markets": {"tulsa_ok": {"cities": ["Tulsa"]}},
        "finance_title_terms": ["finance"],
        "sources": [
            {"id": "first", "employer": "First Co.", "ats": "Workday"},
            {"id": "second", "employer": "Second Co.", "ats": "Workday"},
        ],
    }
    config_path.write_text(json.dumps(config), encoding="utf-8")
    source_data = {
        "first": [_posting("first", "A", "Finance Analyst")],
        "second": [_posting("second", "B", "Office Coordinator")],
    }
    fail_second = False

    def fake_fetch(source, _config, _run_date):
        if source["id"] == "second" and fail_second:
            raise SourceFetchError("board temporarily unavailable", {"postings": source_data["second"]})
        return {"postings": list(source_data[source["id"]]), "total": len(source_data[source["id"]]), "raw_pages": [], "raw_details": [], "warnings": []}

    monkeypatch.setattr("job_watcher.pipeline.fetch_source", fake_fetch)
    raw_dir = root / "raw"
    history_path = root / "history.csv"
    status_path = root / "status.json"
    changes_path = root / "daily_changes.md"

    initial = run_pipeline(config_path, raw_dir, history_path, status_path, changes_path, run_date=date(2026, 11, 9))
    assert initial["status"]["days_with_success"] == 1
    assert initial["status"]["new_today"] == 0
    assert initial["status"]["open"] == 2

    source_data["first"] = [
        _posting("first", "A", "Finance Analyst"),
        _posting("first", "C", "Finance Associate"),
    ]
    fail_second = True
    updated = run_pipeline(config_path, raw_dir, history_path, status_path, changes_path, run_date=date(2026, 11, 10))
    assert updated["status"]["days_with_success"] == 2
    assert updated["status"]["first_run_date"] == "2026-11-09"
    assert updated["status"]["new_today"] == 1
    assert updated["status"]["removed_today"] == 0
    assert updated["status"]["open"] == 3
    assert updated["status"]["sources"][1]["name"] == "Second Co."
    assert updated["status"]["sources"][1]["ok"] is False
    assert updated["status"]["sources"][1]["count"] == 0
    assert not (raw_dir / "2026-11-10" / "second.json.gz").exists()

    with gzip.open(raw_dir / "2026-11-10" / "first.json.gz", "rt", encoding="utf-8") as handle:
        assert json.load(handle)["success"] is True
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert {"run_time", "first_run_date", "days_with_success", "open", "new_today", "removed_today", "sources"} <= status.keys()
    assert all({"name", "ok", "count"} <= entry.keys() for entry in status["sources"])

    # A same-day rerun removes stale files before collecting. If the first
    # source now fails, its prior same-day response must not survive.
    source_data["second"] = [_posting("second", "B", "Office Coordinator")]
    fail_second = False
    monkeypatch.setattr(
        "job_watcher.pipeline.fetch_source",
        lambda source, config, day: (_ for _ in ()).throw(SourceFetchError("first board failed"))
        if source["id"] == "first"
        else fake_fetch(source, config, day),
    )
    rerun = run_pipeline(config_path, raw_dir, history_path, status_path, changes_path, run_date=date(2026, 11, 10))
    assert rerun["status"]["days_with_success"] == 2
    assert not (raw_dir / "2026-11-10" / "first.json.gz").exists()


def test_pipeline_reports_a_reopened_posting_as_new_again(tmp_path, monkeypatch):
    root = tmp_path
    config_path = root / "sources.json"
    config = {
        "markets": {"tulsa_ok": {"cities": ["Tulsa"]}},
        "finance_title_terms": ["finance"],
        "sources": [{"id": "sample", "employer": "Sample Co.", "ats": "Workday"}],
    }
    config_path.write_text(json.dumps(config), encoding="utf-8")
    posting = _posting("sample", "A", "Finance Analyst")
    postings = [posting]

    def fake_fetch(_source, _config, _run_date):
        return {"postings": list(postings), "total": len(postings), "raw_pages": [], "raw_details": [], "warnings": []}

    monkeypatch.setattr("job_watcher.pipeline.fetch_source", fake_fetch)
    raw_dir = root / "raw"
    history_path = root / "history.csv"
    status_path = root / "status.json"
    changes_path = root / "daily_changes.md"

    run_pipeline(config_path, raw_dir, history_path, status_path, changes_path, run_date=date(2026, 11, 9))
    postings = []
    removed = run_pipeline(config_path, raw_dir, history_path, status_path, changes_path, run_date=date(2026, 11, 10))
    assert removed["status"]["removed_today"] == 1

    postings = [posting]
    reopened = run_pipeline(config_path, raw_dir, history_path, status_path, changes_path, run_date=date(2026, 11, 11))
    row = reopened["status"]
    assert row["new_today"] == 1
    assert row["new_today_ids"] == ["sample:A"]
    assert reopened["new_jobs"][0]["first_seen"] == "2026-11-09"
    assert reopened["new_jobs"][0]["last_seen"] == "2026-11-11"

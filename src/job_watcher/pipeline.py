"""Run the daily collector, store raw snapshots, rebuild history, and summarize changes."""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .history import rebuild_history, successful_run_dates
from .sources import SourceFetchError, fetch_source


def _write_json_gz(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        json.dump(document, handle, ensure_ascii=False, separators=(",", ":"))


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def _change_report(
    run_date: str,
    baseline: bool,
    new_jobs: list[dict[str, str]],
    removed_jobs: list[dict[str, str]],
    source_results: list[dict[str, Any]],
) -> str:
    lines = [f"# Job Watcher updates — {run_date}", ""]
    successes = sum(1 for result in source_results if result["ok"])
    lines.append(f"Employer boards collected successfully: **{successes} of {len(source_results)}**.")
    if baseline:
        lines.append("This is the initial collection. Existing postings establish the baseline and are not counted as new.")
    lines.append(f"New or reopened postings: **{len(new_jobs)}**")
    lines.append(f"Removed postings: **{len(removed_jobs)}**")
    for heading, jobs in (("New or reopened postings", new_jobs), ("Removed postings", removed_jobs)):
        if not jobs:
            continue
        lines.extend(["", f"## {heading}", ""])
        for job in jobs[:30]:
            title = job.get("title") or "Untitled role"
            employer = job.get("employer") or "Employer"
            location = job.get("location") or "Location not provided"
            market = job.get("market") or ""
            url = job.get("url") or ""
            label = f"[{title}]({url})" if url.startswith(("https://", "http://")) else title
            details = [f"**{employer}**", location]
            if market:
                details.append(market.replace(";", ", "))
            lines.append(f"- {label} — " + " · ".join(details))
        if len(jobs) > 30:
            lines.append(f"- …and {len(jobs) - 30} more. See `data/history.csv` for the full list.")
    if not new_jobs and not removed_jobs:
        lines.extend(["", "No new or removed postings were recorded in this run."])
    failed = [result for result in source_results if not result["success"]]
    if failed:
        lines.extend(["", "## Sources that need attention", ""])
        lines.extend(f"- **{item['employer']}** (`{item['source_id']}`): {item.get('error') or 'request failed'}" for item in failed)
    return "\n".join(lines) + "\n"


def _new_or_reopened_postings(
    raw_dir: Path, run_date_text: str, rows: list[dict[str, str]]
) -> list[dict[str, str]]:
    """Find IDs newly present in today's successful snapshots vs each source's previous success."""

    changed_ids: set[str] = set()
    today_dir = raw_dir / run_date_text
    if not today_dir.exists():
        return []

    for current_path in today_dir.glob("*.json.gz"):
        with gzip.open(current_path, "rt", encoding="utf-8") as handle:
            current = json.load(handle)
        if not current.get("success"):
            continue
        source_id = str(current.get("source_id") or current_path.stem)
        previous_snapshots = []
        for path in raw_dir.glob(f"*/{source_id}.json.gz"):
            if path.parent.name >= run_date_text:
                continue
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                snapshot = json.load(handle)
            if snapshot.get("success"):
                previous_snapshots.append((str(snapshot.get("run_date") or path.parent.name), snapshot))
        if not previous_snapshots:
            continue
        previous = max(previous_snapshots, key=lambda item: item[0])[1]
        previous_ids = {
            str(posting.get("posting_id") or "")
            for posting in previous.get("postings", [])
            if posting.get("posting_id")
        }
        current_ids = {
            str(posting.get("posting_id") or "")
            for posting in current.get("postings", [])
            if posting.get("posting_id")
        }
        changed_ids.update(current_ids - previous_ids)

    by_id = {row["posting_id"]: row for row in rows}
    return sorted(
        (
            by_id[posting_id]
            for posting_id in changed_ids
            if posting_id in by_id
            and by_id[posting_id]["status"] == "open"
        ),
        key=lambda row: row["posting_id"],
    )


def _set_github_output(name: str, value: str) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def run_pipeline(
    config_path: Path,
    raw_dir: Path,
    history_path: Path,
    status_path: Path,
    changes_path: Path,
    run_date: date | None = None,
) -> dict[str, Any]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    run_date = run_date or datetime.now(timezone.utc).date()
    run_date_text = run_date.isoformat()
    run_time = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    previous_success_dates = successful_run_dates(raw_dir) if raw_dir.exists() else []
    baseline = not previous_success_dates
    daily_dir = raw_dir / run_date_text
    daily_dir.mkdir(parents=True, exist_ok=True)
    # A rerun replaces this date's active-source snapshots so an old success
    # cannot survive a later failure. Snapshots from inactive sources stay archived.
    active_source_ids = {str(source["id"]) for source in config.get("sources", [])}
    for old_snapshot in daily_dir.glob("*.json.gz"):
        if old_snapshot.stem in active_source_ids:
            old_snapshot.unlink()

    source_results: list[dict[str, Any]] = []
    for source in config.get("sources", []):
        started = time.monotonic()
        raw_result: dict[str, Any] = {"raw_pages": [], "raw_details": [], "postings": [], "warnings": []}
        error = ""
        try:
            raw_result = fetch_source(source, config, run_date)
            success = True
        except Exception as exc:  # Keep the rest of the employer boards running.
            success = False
            error = f"{type(exc).__name__}: {exc}"[:1000]

        elapsed = round(time.monotonic() - started, 2)
        envelope = {
            "run_date": run_date_text,
            "fetched_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "source_id": source["id"],
            "source_name": source["employer"],
            "ats": source.get("ats", ""),
            "employer": source["employer"],
            "success": success,
            "total": raw_result.get("total", len(raw_result.get("postings", []))),
            "postings": raw_result.get("postings", []),
            "raw_pages": raw_result.get("raw_pages", []),
            "raw_details": raw_result.get("raw_details", []),
            "warnings": raw_result.get("warnings", []),
            "error": error,
        }
        if success:
            _write_json_gz(daily_dir / f"{source['id']}.json.gz", envelope)
        source_results.append(
            {
                # Required status fields, plus diagnostic details used by the site.
                "name": source["employer"],
                "ok": success,
                "count": len(envelope["postings"]) if success else 0,
                "source_id": source["id"],
                "employer": source["employer"],
                "success": success,
                "postings": len(envelope["postings"]) if success else 0,
                "total": envelope["total"] if success else 0,
                "warnings": len(envelope["warnings"]) if success else 0,
                "error": error,
                "elapsed_seconds": elapsed,
            }
        )
        state = "ok" if success else "FAILED"
        print(f"{state:6} {source['id']}: {len(envelope['postings'])}/{envelope['total']} postings ({elapsed}s)")
        if error:
            print(f"       {error}", file=sys.stderr)

    rows = rebuild_history(raw_dir, history_path, config)
    new_jobs = _new_or_reopened_postings(raw_dir, run_date_text, rows)
    removed_jobs = [
        row
        for row in rows
        if row.get("status") == "removed"
        and row.get("removed_date") == run_date_text
    ]

    dates_with_success = successful_run_dates(raw_dir)
    first_run_date = dates_with_success[0] if dates_with_success else None
    first_collection = baseline and any(result["ok"] for result in source_results)
    issue_changes = bool(new_jobs or removed_jobs) and not first_collection
    open_postings = sum(1 for row in rows if row["status"] == "open")
    summary = {
        "run_time": run_time,
        "run_date": run_date_text,
        "first_run_date": first_run_date,
        "days_with_success": len(dates_with_success),
        "open": open_postings,
        "new_today": 0 if first_collection else len(new_jobs),
        "new_today_ids": [] if first_collection else [row["posting_id"] for row in new_jobs],
        "removed_today": len(removed_jobs),
        "sources": source_results,
    }
    _write_json(status_path, summary)
    changes_path.parent.mkdir(parents=True, exist_ok=True)
    changes_path.write_text(_change_report(run_date_text, first_collection, new_jobs, removed_jobs, source_results), encoding="utf-8")
    _set_github_output("changes", str(issue_changes).lower())
    _set_github_output("new_count", str(len(new_jobs) if not first_collection else 0))
    _set_github_output("removed_count", str(len(removed_jobs)))

    failures = sum(1 for result in source_results if not result["success"])
    successes = len(source_results) - failures
    print(f"Run {run_date_text}: {successes}/{len(source_results)} sources succeeded; {open_postings} open postings.")
    return {"status": summary, "new_jobs": new_jobs, "removed_jobs": removed_jobs, "issue_changes": issue_changes, "failures": failures}


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch public finance job boards and update local history.")
    parser.add_argument("--config", type=Path, default=Path("config/sources.json"))
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--history", type=Path, default=Path("data/history.csv"))
    parser.add_argument("--status", type=Path, default=Path("data/status.json"))
    parser.add_argument("--changes", type=Path, default=Path("data/daily_changes.md"))
    parser.add_argument("--build-only", action="store_true", help="Rebuild history from saved raw snapshots without fetching job boards.")
    args = parser.parse_args()
    if args.build_only:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        rows = rebuild_history(args.raw_dir, args.history, config)
        print(f"Rebuilt {args.history} from {args.raw_dir}: {len(rows)} postings.")
        return 0
    result = run_pipeline(args.config, args.raw_dir, args.history, args.status, args.changes)
    # A partial collection is useful and recorded; fail only when every source fails.
    return 0 if result["failures"] < len(result["status"]["sources"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())

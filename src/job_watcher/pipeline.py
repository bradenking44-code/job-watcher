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

from .history import market_ids_for_location, read_history, rebuild_history, successful_run_dates
from .sources import SourceFetchError, fetch_source


def _write_json_gz(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        json.dump(document, handle, ensure_ascii=False, separators=(",", ":"))


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def _is_local_role(row: dict[str, Any]) -> bool:
    return row.get("in_role") == "true" and row.get("in_market") == "true"


def _change_report(
    run_date: str,
    baseline: bool,
    new_jobs: list[dict[str, str]],
    removed_jobs: list[dict[str, str]],
    source_results: list[dict[str, Any]],
) -> str:
    if baseline:
        successes = sum(1 for result in source_results if result["success"])
        return (
            f"# Job Watcher — {run_date}\n\n"
            "This was the initial data collection, so it establishes a baseline rather than sending a new-job alert.\n\n"
            f"Successful employer boards: **{successes} of {len(source_results)}**.\n"
        )

    lines = [f"# Job Watcher changes — {run_date}", ""]
    lines.append(f"New local finance matches: **{len(new_jobs)}**  ")
    lines.append(f"Removed local finance matches: **{len(removed_jobs)}**")
    for heading, jobs in (("New postings", new_jobs), ("Removed postings", removed_jobs)):
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
            lines.append(f"- {label} — **{employer}** · {location} · {market.replace(';', ', ')}")
        if len(jobs) > 30:
            lines.append(f"- …and {len(jobs) - 30} more. See `data/history.csv` for the full list.")
    failed = [result for result in source_results if not result["success"]]
    if failed:
        lines.extend(["", "## Sources that need attention", ""])
        lines.extend(f"- **{item['employer']}** (`{item['source_id']}`): {item.get('error') or 'request failed'}" for item in failed)
    return "\n".join(lines) + "\n"


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
    prior_rows = read_history(history_path)
    prior_by_id = {row.get("posting_id", ""): row for row in prior_rows}
    daily_dir = raw_dir / run_date_text
    daily_dir.mkdir(parents=True, exist_ok=True)

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
            partial = getattr(exc, "partial", None)
            if isinstance(partial, dict):
                raw_result.update(partial)

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
        _write_json_gz(daily_dir / f"{source['id']}.json.gz", envelope)
        source_results.append(
            {
                "source_id": source["id"],
                "employer": source["employer"],
                "success": success,
                "postings": len(envelope["postings"]),
                "total": envelope["total"],
                "warnings": len(envelope["warnings"]),
                "error": error,
                "elapsed_seconds": elapsed,
            }
        )
        state = "ok" if success else "FAILED"
        print(f"{state:6} {source['id']}: {len(envelope['postings'])}/{envelope['total']} postings ({elapsed}s)")
        if error:
            print(f"       {error}", file=sys.stderr)

    rows = rebuild_history(raw_dir, history_path, config)
    current_by_id = {row["posting_id"]: row for row in rows}
    new_jobs = []
    for posting_id, row in current_by_id.items():
        prior = prior_by_id.get(posting_id)
        if not _is_local_role(row) or row["status"] != "open":
            continue
        if prior is None or prior.get("status") == "removed" or prior.get("in_role") != "true" or prior.get("in_market") != "true":
            new_jobs.append(row)
    removed_jobs = [
        row
        for posting_id, row in current_by_id.items()
        if row.get("status") == "removed"
        and row.get("removed_date") == run_date_text
        and _is_local_role(row)
        and prior_by_id.get(posting_id, {}).get("status") == "open"
        and _is_local_role(prior_by_id.get(posting_id, {}))
    ]

    dates_with_success = successful_run_dates(raw_dir)
    first_run_date = dates_with_success[0] if dates_with_success else None
    first_collection = baseline and any(result["success"] for result in source_results)
    issue_changes = bool(new_jobs or removed_jobs) and not first_collection
    open_local_roles = sum(1 for row in rows if row["status"] == "open" and _is_local_role(row))
    summary = {
        "run_time": run_time,
        "run_date": run_date_text,
        "first_run_date": first_run_date,
        "days_with_success": len(dates_with_success),
        "open": open_local_roles,
        "new_today": 0 if first_collection else len(new_jobs),
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
    print(f"Run {run_date_text}: {successes}/{len(source_results)} sources succeeded; {open_local_roles} open local finance matches.")
    return {"status": summary, "new_jobs": new_jobs, "removed_jobs": removed_jobs, "issue_changes": issue_changes, "failures": failures}


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch public finance job boards and update local history.")
    parser.add_argument("--config", type=Path, default=Path("config/sources.json"))
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--history", type=Path, default=Path("data/history.csv"))
    parser.add_argument("--status", type=Path, default=Path("data/status.json"))
    parser.add_argument("--changes", type=Path, default=Path("data/daily_changes.md"))
    args = parser.parse_args()
    result = run_pipeline(args.config, args.raw_dir, args.history, args.status, args.changes)
    return 0 if any(source["success"] for source in result["status"]["sources"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())

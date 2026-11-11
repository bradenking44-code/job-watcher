"""Deterministically rebuild posting history from compressed raw snapshots."""

from __future__ import annotations

import csv
import gzip
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


FIELDNAMES = [
    "posting_id",
    "source",
    "source_id",
    "employer",
    "title",
    "location",
    "department",
    "posted_date",
    "url",
    "in_role",
    "in_market",
    "market",
    "first_run",
    "first_seen",
    "last_seen",
    "status",
    "removed_date",
]


def title_matches(title: str, terms: list[str]) -> bool:
    normalized = str(title or "").casefold()
    for term in terms:
        pattern = r"\b" + re.escape(str(term).casefold()) + r"[a-z]*\b"
        if re.search(pattern, normalized):
            return True
    return False


def market_ids_for_location(location: str, markets: dict[str, Any]) -> list[str]:
    normalized = str(location or "").casefold()
    matches = []
    for market_id, market in markets.items():
        for city in market.get("cities", []):
            if re.search(r"(?<!\w)" + re.escape(str(city).casefold()) + r"(?!\w)", normalized):
                matches.append(market_id)
                break
    if not matches and re.search(r"\b(remote|work from home)\b", normalized):
        if re.search(r"\b(oklahoma|ok)\b", normalized) and "tulsa_ok" in markets:
            matches.append("tulsa_ok")
        if re.search(r"\b(arkansas|ar)\b", normalized) and "northwest_ar" in markets:
            matches.append("northwest_ar")
    return matches


def read_history(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_raw_snapshots(
    raw_dir: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]], dict[str, list[str]], list[str]]:
    """Return latest posting fields, observed dates, and successful source dates."""

    latest: dict[str, dict[str, Any]] = {}
    observed: dict[str, list[str]] = defaultdict(list)
    successful: dict[str, set[str]] = defaultdict(set)
    successful_run_dates: set[str] = set()

    for path in sorted(raw_dir.rglob("*.json.gz")):
        try:
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                snapshot = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Cannot read raw snapshot {path}: {exc}") from exc

        run_date = str(snapshot.get("run_date") or path.parent.name)[:10]
        source_id = str(snapshot.get("source_id") or path.stem)
        if not snapshot.get("success"):
            continue
        successful[source_id].add(run_date)
        successful_run_dates.add(run_date)

        for posting in snapshot.get("postings") or []:
            posting_id = str(posting.get("posting_id") or "").strip()
            if not posting_id:
                continue
            observed[posting_id].append(run_date)
            # Files sort by date, so this retains the newest known fields.
            latest[posting_id] = {
                **posting,
                "source_id": source_id,
                "employer": str(snapshot.get("employer") or posting.get("employer") or ""),
                "source": str(snapshot.get("ats") or ""),
                "source_name": str(snapshot.get("source_name") or ""),
            }

    source_success_dates = {source_id: sorted(dates) for source_id, dates in successful.items()}
    return latest, observed, source_success_dates, sorted(successful_run_dates)


def rebuild_history(raw_dir: Path, output_path: Path, config: dict[str, Any]) -> list[dict[str, str]]:
    """Rebuild the CSV using only raw snapshots and the stable source config."""

    latest, observed, source_success_dates, successful_run_dates = load_raw_snapshots(raw_dir)
    markets = config.get("markets", {})
    terms = config.get("finance_title_terms", [])
    first_success_by_source = {
        source_id: dates[0] for source_id, dates in source_success_dates.items() if dates
    }
    inactive_source_ids = {str(source_id) for source_id in config.get("inactive_source_ids", [])}
    rows: list[dict[str, str]] = []

    for posting_id in sorted(latest):
        posting = latest[posting_id]
        dates = sorted(set(observed[posting_id]))
        first_seen = dates[0]
        last_seen = dates[-1]
        source_id = str(posting.get("source_id") or "")
        next_success = next((day for day in source_success_dates.get(source_id, []) if day > last_seen), "")
        archived = source_id in inactive_source_ids
        location = str(posting.get("location") or "")
        market_ids = market_ids_for_location(location, markets)
        row = {
            "posting_id": posting_id,
            "source": str(posting.get("source") or ""),
            "source_id": str(posting.get("external_id") or posting_id),
            "employer": str(posting.get("employer") or ""),
            "title": str(posting.get("title") or ""),
            "location": location,
            "department": str(posting.get("department") or ""),
            "posted_date": str(posting.get("posted_date") or first_seen),
            "url": str(posting.get("url") or ""),
            "in_role": str(title_matches(str(posting.get("title") or ""), terms)).lower(),
            "in_market": str(bool(market_ids)).lower(),
            "market": ";".join(market_ids),
            "first_run": str(first_seen == first_success_by_source.get(source_id, "")).lower(),
            "first_seen": first_seen,
            "last_seen": last_seen,
            "status": "archived" if archived else "removed" if next_success else "open",
            "removed_date": "" if archived else next_success,
        }
        rows.append(row)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return rows


def successful_run_dates(raw_dir: Path) -> list[str]:
    """List distinct UTC run dates with at least one successful source."""

    dates: set[str] = set()
    for path in sorted(raw_dir.rglob("*.json.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            snapshot = json.load(handle)
        if snapshot.get("success"):
            dates.add(str(snapshot.get("run_date") or path.parent.name)[:10])
    return sorted(dates)

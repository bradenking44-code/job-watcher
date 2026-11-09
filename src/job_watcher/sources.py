"""Public job-board adapters for Workday CXS and Oracle Candidate Experience."""

from __future__ import annotations

import json
import re
import time
from datetime import date, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


USER_AGENT = "job-watcher/0.1 (+https://github.com/bradenking44-code/job-watcher)"
TIMEOUT_SECONDS = 30
MAX_PAGES = 1000


class SourceFetchError(RuntimeError):
    """Raised when an employer's public job board cannot be read completely."""

    def __init__(self, message: str, partial: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.partial = partial or {}


def request_json(url: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Read a public JSON endpoint, retrying transient HTTP and network failures."""

    payload = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    if payload is not None:
        headers["Content-Type"] = "application/json"
    request = Request(url, data=payload, headers=headers, method="POST" if payload is not None else "GET")

    for attempt in range(4):
        try:
            with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                decoded = response.read().decode("utf-8")
            result = json.loads(decoded)
            if not isinstance(result, dict):
                raise SourceFetchError(f"Expected a JSON object from {url}")
            return result
        except HTTPError as exc:
            transient = exc.code == 429 or 500 <= exc.code < 600
            if not transient or attempt == 3:
                raise SourceFetchError(f"HTTP {exc.code} from {url}") from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            if attempt == 3:
                raise SourceFetchError(f"Could not read JSON from {url}: {exc}") from exc
        time.sleep(min(2**attempt, 8))
    raise SourceFetchError(f"Could not read JSON from {url}")


def parse_posted_date(value: Any, run_date: date) -> str:
    """Convert source dates and relative Workday labels to an ISO date."""

    raw = str(value or "").strip()
    if not raw:
        return ""
    for candidate in (raw, raw[:10]):
        try:
            return date.fromisoformat(candidate).isoformat()
        except ValueError:
            pass
    for pattern, days in ((r"today", 0), (r"yesterday", 1)):
        if re.search(pattern, raw, re.IGNORECASE):
            return (run_date - timedelta(days=days)).isoformat()
    match = re.search(r"(\d+)\s+days?\s+ago", raw, re.IGNORECASE)
    if match:
        return (run_date - timedelta(days=int(match.group(1)))).isoformat()
    for fmt in ("%m/%d/%Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            return date.fromisoformat(time.strftime("%Y-%m-%d", time.strptime(raw, fmt))).isoformat()
        except ValueError:
            pass
    return ""


def _workday_id(item: dict[str, Any]) -> str:
    bullets = item.get("bulletFields") or []
    if bullets:
        return str(bullets[0])
    path = str(item.get("externalPath") or "")
    return path.rsplit("_", 1)[-1] if "_" in path else path


def _needs_location_detail(value: str) -> bool:
    return bool(re.fullmatch(r"\s*(?:\d+\s+locations?|multiple locations|various locations)\s*", value, re.IGNORECASE))


def _location_from_workday_detail(detail: dict[str, Any]) -> str:
    info = detail.get("jobPostingInfo") or {}
    values: list[str] = []
    for value in [info.get("location"), *(info.get("additionalLocations") or [])]:
        if isinstance(value, str) and value.strip() and value not in values:
            values.append(value.strip())
    return "; ".join(values)


def fetch_workday(
    source: dict[str, Any],
    request_config: dict[str, Any],
    run_date: date,
) -> dict[str, Any]:
    """Fetch every Workday CXS posting and enrich generic multi-location labels."""

    endpoint = source["api_endpoint"]
    body_template = request_config.get("body_template", {})
    page_size = max(1, int(body_template.get("limit", 100)))
    offset = 0
    pages: list[dict[str, Any]] = []
    raw_details: list[dict[str, Any]] = []
    postings: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    total: int | None = None
    warnings: list[str] = []

    for _ in range(MAX_PAGES):
        body = dict(body_template)
        body["limit"] = page_size
        body["offset"] = offset
        try:
            page = request_json(endpoint, body)
        except SourceFetchError as exc:
            partial = {"raw_pages": pages, "raw_details": raw_details, "postings": postings, "warnings": warnings, "total": total}
            raise SourceFetchError(str(exc), partial) from exc
        pages.append(page)
        items = page.get("jobPostings")
        if not isinstance(items, list):
            raise SourceFetchError(f"Workday response did not contain jobPostings for {source['id']}")
        # Some Workday boards report their real count only on the first page
        # and return 0 on subsequent pages. Keep the largest positive count.
        try:
            reported_total = int(page.get("total", 0))
        except (TypeError, ValueError):
            reported_total = 0
        if reported_total > 0:
            total = max(total or 0, reported_total)
        if not items:
            break

        for item in items:
            if not isinstance(item, dict):
                continue
            external_id = _workday_id(item)
            unique_id = f"{source['id']}:{external_id}"
            if unique_id in seen_ids:
                continue
            seen_ids.add(unique_id)
            external_path = str(item.get("externalPath") or "")
            location = str(item.get("locationsText") or "").strip()
            if request_config.get("detail_for_multi_location_results", True) and _needs_location_detail(location) and external_path:
                detail_url = endpoint.rsplit("/jobs", 1)[0] + external_path
                try:
                    detail = request_json(detail_url)
                    raw_details.append({"external_path": external_path, "response": detail})
                    detailed_locations = _location_from_workday_detail(detail)
                    if detailed_locations:
                        location = detailed_locations
                except SourceFetchError as exc:
                    warnings.append(f"Location detail unavailable for {external_id}: {exc}")

            career_url = str(source.get("career_url") or "").rstrip("/")
            job_url = f"{career_url}{external_path}" if external_path else career_url
            posted_on = item.get("postedOn")
            postings.append(
                {
                    "posting_id": unique_id,
                    "external_id": external_id,
                    "title": str(item.get("title") or "").strip(),
                    "location": location,
                    "department": str(item.get("department") or item.get("jobFamilyGroup") or "").strip(),
                    "posted_date": parse_posted_date(posted_on, run_date),
                    "posted_label": str(posted_on or ""),
                    "url": job_url,
                }
            )

        offset += len(items)
        if (total is not None and offset >= total) or len(items) < page_size:
            break
    else:
        raise SourceFetchError(
            f"Pagination safety limit reached for {source['id']}",
            {"raw_pages": pages, "raw_details": raw_details, "postings": postings, "warnings": warnings, "total": total},
        )

    if total is not None and len(seen_ids) < total:
        raise SourceFetchError(
            f"Fetched {len(seen_ids)} of {total} Workday postings for {source['id']}",
            {"raw_pages": pages, "raw_details": raw_details, "postings": postings, "warnings": warnings, "total": total},
        )

    return {
        "postings": postings,
        "total": total if total is not None else len(postings),
        "raw_pages": pages,
        "raw_details": raw_details,
        "warnings": warnings,
    }


def _oracle_locations(item: dict[str, Any]) -> str:
    values: list[str] = []
    primary = item.get("PrimaryLocation")
    if isinstance(primary, str) and primary.strip():
        values.append(primary.strip())
    for secondary in item.get("secondaryLocations") or []:
        if isinstance(secondary, str):
            candidate = secondary.strip()
        elif isinstance(secondary, dict):
            candidate = str(
                secondary.get("LocationName")
                or secondary.get("Location")
                or secondary.get("locationName")
                or secondary.get("location")
                or secondary.get("Name")
                or ""
            ).strip()
        else:
            candidate = ""
        if candidate and candidate not in values:
            values.append(candidate)
    return "; ".join(values)


def fetch_oracle_candidate_experience(
    source: dict[str, Any],
    request_config: dict[str, Any],
    run_date: date,
) -> dict[str, Any]:
    """Fetch a public Oracle Candidate Experience jobs site with offset pagination."""

    endpoint = source["api_endpoint"]
    site_number = source["site_number"]
    page_size = max(1, int(request_config.get("page_size", 100)))
    expand = str(request_config.get("expand", "requisitionList.secondaryLocations"))
    sort_by = str(request_config.get("sort_by", "POSTING_DATES_DESC"))
    offset = 0
    total: int | None = None
    pages: list[dict[str, Any]] = []
    postings: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for _ in range(MAX_PAGES):
        finder = f"findReqs;siteNumber={site_number},limit={page_size},offset={offset},sortBy={sort_by}"
        query = f"onlyData=true&expand={quote(expand, safe='')}&finder={quote(finder, safe=';,=')}"
        try:
            page = request_json(f"{endpoint}?{query}")
        except SourceFetchError as exc:
            partial = {"raw_pages": pages, "raw_details": [], "postings": postings, "total": total, "warnings": []}
            raise SourceFetchError(str(exc), partial) from exc
        pages.append(page)
        envelopes = page.get("items") or []
        if not envelopes:
            break
        envelope = envelopes[0]
        rows = envelope.get("requisitionList") or []
        try:
            reported_total = int(envelope.get("TotalJobsCount", page.get("count", 0)))
        except (TypeError, ValueError):
            reported_total = 0
        if reported_total > 0:
            total = max(total or 0, reported_total)
        if not rows:
            break

        career_url = str(source.get("career_url") or "").rstrip("/")
        for item in rows:
            if not isinstance(item, dict):
                continue
            external_id = str(item.get("Id") or item.get("RequisitionNumber") or "").strip()
            if not external_id:
                continue
            unique_id = f"{source['id']}:{external_id}"
            if unique_id in seen_ids:
                continue
            seen_ids.add(unique_id)
            locations = _oracle_locations(item)
            department = item.get("Department") or item.get("JobFamily") or item.get("JobFunction") or ""
            postings.append(
                {
                    "posting_id": unique_id,
                    "external_id": external_id,
                    "title": str(item.get("Title") or "").strip(),
                    "location": locations,
                    "department": str(department).strip(),
                    "posted_date": parse_posted_date(item.get("PostedDate"), run_date),
                    "posted_label": str(item.get("PostedDate") or ""),
                    "url": f"{career_url}/job/{quote(external_id)}",
                }
            )

        offset += len(rows)
        has_more = page.get("hasMore")
        if has_more is False or (total is not None and offset >= total):
            break
        if has_more is None and len(rows) < page_size:
            break
    else:
        raise SourceFetchError(
            f"Pagination safety limit reached for {source['id']}",
            {"raw_pages": pages, "raw_details": [], "postings": postings, "total": total, "warnings": []},
        )

    if total is not None and len(seen_ids) < total:
        raise SourceFetchError(
            f"Fetched {len(seen_ids)} of {total} Oracle postings for {source['id']}",
            {"raw_pages": pages, "raw_details": [], "postings": postings, "total": total, "warnings": []},
        )

    return {"postings": postings, "total": total if total is not None else len(postings), "raw_pages": pages, "raw_details": [], "warnings": []}


def fetch_source(source: dict[str, Any], config: dict[str, Any], run_date: date) -> dict[str, Any]:
    api_type = source.get("api_type")
    if api_type == "oracle_candidate_experience":
        return fetch_oracle_candidate_experience(source, config.get("oracle_request", {}), run_date)
    if api_type == "workday_cxs" or source.get("ats", "").lower() == "workday":
        return fetch_workday(source, config.get("workday_request", {}), run_date)
    raise SourceFetchError(f"Unsupported public job-board adapter: {api_type or source.get('ats')} for {source['id']}")

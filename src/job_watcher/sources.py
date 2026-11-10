"""Public structured-data adapters for supported employer job boards."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import http.cookiejar
import json
import re
import time
from datetime import date, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, HTTPCookieProcessor, Request, build_opener, urlopen
from xml.etree import ElementTree


USER_AGENT = "job-watcher/0.1 (+https://github.com/bradenking44-code/job-watcher)"
INFOR_USER_AGENT = "Mozilla/5.0 (compatible; JobWatcher/0.1; +https://github.com/bradenking44-code/job-watcher)"
TIMEOUT_SECONDS = 30
MAX_PAGES = 1000


class SourceFetchError(RuntimeError):
    """Raised when an employer's public job board cannot be read completely."""

    def __init__(self, message: str, partial: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.partial = partial or {}


class _NoRedirectHandler(HTTPRedirectHandler):
    """Leave redirects visible so Infor's anonymous assertion can reuse cookies."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


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


def request_text(url: str) -> str:
    """Read a public text feed, retrying transient HTTP and network failures."""

    request = Request(
        url,
        headers={"Accept": "application/rss+xml, application/xml, text/xml", "User-Agent": USER_AGENT},
    )
    for attempt in range(4):
        try:
            with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                return response.read().decode("utf-8-sig")
        except HTTPError as exc:
            transient = exc.code == 429 or 500 <= exc.code < 600
            if not transient or attempt == 3:
                raise SourceFetchError(f"HTTP {exc.code} from {url}") from exc
        except (URLError, TimeoutError) as exc:
            if attempt == 3:
                raise SourceFetchError(f"Could not read feed from {url}: {exc}") from exc
        time.sleep(min(2**attempt, 8))
    raise SourceFetchError(f"Could not read feed from {url}")


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
    pages: list[dict[str, Any]] = []
    raw_details: list[dict[str, Any]] = []
    postings: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    total: int | None = None
    warnings: list[str] = []
    duplicate_items = 0

    sweep = 0
    while True:
        offset = 0
        pass_ids: set[str] = set()
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

            page_new_ids = 0
            detail_tasks: list[tuple[int, str, str, str]] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                external_id = _workday_id(item)
                unique_id = f"{source['id']}:{external_id}"
                if unique_id in pass_ids:
                    duplicate_items += 1
                    continue
                pass_ids.add(unique_id)
                page_new_ids += 1
                if unique_id in seen_ids:
                    continue
                seen_ids.add(unique_id)
                external_path = str(item.get("externalPath") or "")
                location = str(item.get("locationsText") or "").strip()
                if request_config.get("detail_for_multi_location_results", True) and _needs_location_detail(location) and external_path:
                    detail_url = endpoint.rsplit("/jobs", 1)[0] + external_path
                    detail_tasks.append((len(postings), external_id, external_path, detail_url))

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

            # Large boards can have hundreds of generic multi-location labels.
            # Fetch each page's details with a small concurrency cap instead of
            # serializing every extra request across the entire board.
            if detail_tasks:
                with ThreadPoolExecutor(max_workers=min(4, len(detail_tasks))) as detail_pool:
                    futures = [
                        (posting_index, external_id, external_path, detail_pool.submit(request_json, detail_url))
                        for posting_index, external_id, external_path, detail_url in detail_tasks
                    ]
                    for posting_index, external_id, external_path, future in futures:
                        try:
                            detail = future.result()
                            raw_details.append({"external_path": external_path, "response": detail})
                            detailed_locations = _location_from_workday_detail(detail)
                            if detailed_locations:
                                postings[posting_index]["location"] = detailed_locations
                        except SourceFetchError as exc:
                            warnings.append(f"Location detail unavailable for {external_id}: {exc}")

            # Offset results can overlap while a large board changes. Move by
            # the new IDs within this sweep, and repeat the sweep once if that
            # drift still leaves fewer unique postings than Workday reported.
            offset += max(page_new_ids, 1)
            if total is not None and len(pass_ids) >= total:
                break
            if total is None and len(items) < page_size:
                break
        else:
            raise SourceFetchError(
                f"Pagination safety limit reached for {source['id']}",
                {"raw_pages": pages, "raw_details": raw_details, "postings": postings, "warnings": warnings, "total": total},
            )

        if total is None or len(pass_ids) >= total:
            break
        if sweep >= 1:
            raise SourceFetchError(
                f"Fetched {len(seen_ids)} of {total} Workday postings for {source['id']} after a repeat scan",
                {"raw_pages": pages, "raw_details": raw_details, "postings": postings, "warnings": warnings, "total": total},
            )
        sweep += 1
        warnings.append(f"Repeated the board scan after {len(pass_ids)} of {total} unique postings were found")

    if duplicate_items:
        warnings.append(f"Skipped {duplicate_items} duplicate postings returned across overlapping pages")

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
    total: int | None = None
    pages: list[dict[str, Any]] = []
    postings: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    warnings: list[str] = []
    duplicate_items = 0

    sweep = 0
    while True:
        offset = 0
        pass_ids: set[str] = set()
        for _ in range(MAX_PAGES):
            finder = f"findReqs;siteNumber={site_number},limit={page_size},offset={offset},sortBy={sort_by}"
            query = f"onlyData=true&expand={quote(expand, safe='')}&finder={quote(finder, safe=';,=')}"
            try:
                page = request_json(f"{endpoint}?{query}")
            except SourceFetchError as exc:
                partial = {"raw_pages": pages, "raw_details": [], "postings": postings, "total": total, "warnings": warnings}
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

            page_new_ids = 0
            career_url = str(source.get("career_url") or "").rstrip("/")
            for item in rows:
                if not isinstance(item, dict):
                    continue
                external_id = str(item.get("Id") or item.get("RequisitionNumber") or "").strip()
                if not external_id:
                    continue
                unique_id = f"{source['id']}:{external_id}"
                if unique_id in pass_ids:
                    duplicate_items += 1
                    continue
                pass_ids.add(unique_id)
                page_new_ids += 1
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

            # Trust a positive total over Oracle's hasMore flag, which can be
            # false before the last offset page during a changing job board.
            offset += max(page_new_ids, 1)
            has_more = page.get("hasMore")
            if total is not None and len(pass_ids) >= total:
                break
            if total is None and has_more is False:
                break
            if total is None and has_more is None and len(rows) < page_size:
                break
        else:
            raise SourceFetchError(
                f"Pagination safety limit reached for {source['id']}",
                {"raw_pages": pages, "raw_details": [], "postings": postings, "total": total, "warnings": warnings},
            )

        if total is None or len(pass_ids) >= total:
            break
        if sweep >= 1:
            raise SourceFetchError(
                f"Fetched {len(seen_ids)} of {total} Oracle postings for {source['id']} after a repeat scan",
                {"raw_pages": pages, "raw_details": [], "postings": postings, "total": total, "warnings": warnings},
            )
        sweep += 1
        warnings.append(f"Repeated the board scan after {len(pass_ids)} of {total} unique postings were found")

    if duplicate_items:
        warnings.append(f"Skipped {duplicate_items} duplicate postings returned across overlapping pages")

    return {"postings": postings, "total": total if total is not None else len(postings), "raw_pages": pages, "raw_details": [], "warnings": warnings}


def fetch_successfactors_rss(source: dict[str, Any]) -> dict[str, Any]:
    """Fetch the public SAP SuccessFactors RSS/XML job feed."""

    feed_text = request_text(source["api_endpoint"])
    try:
        root = ElementTree.fromstring(feed_text)
    except ElementTree.ParseError as exc:
        raise SourceFetchError(f"Invalid RSS/XML response from {source['api_endpoint']}: {exc}") from exc

    channel = root.find("channel")
    if channel is None:
        raise SourceFetchError(f"RSS response did not contain a channel for {source['id']}")

    postings: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in channel.findall("item"):
        external_id = str(item.findtext("id") or item.findtext("guid") or "").strip()
        if not external_id:
            continue
        if external_id in seen_ids:
            continue
        seen_ids.add(external_id)

        title = str(item.findtext("title") or "").strip()
        location = str(item.findtext("location") or "").strip()
        # BOK includes the full location in parentheses in RSS titles as well
        # as in its separate location field. Keep the title clean for role matching.
        location_suffix = f" ({location})" if location else ""
        if location_suffix and title.endswith(location_suffix):
            title = title[: -len(location_suffix)].strip()

        postings.append(
            {
                "posting_id": f"{source['id']}:{external_id}",
                "external_id": external_id,
                "title": title,
                "location": location,
                "department": str(item.findtext("job_function") or "").strip(),
                "posted_date": "",
                "posted_label": "",
                "url": str(item.findtext("link") or source.get("career_url") or "").strip(),
            }
        )

    return {
        "postings": postings,
        "total": len(postings),
        # Preserve the source response as received; the pipeline compresses it
        # with the other public API snapshots.
        "raw_pages": [{"xml": feed_text}],
        "warnings": [],
    }


def request_infor_json(url: str, opener: Any, expected_host: str) -> dict[str, Any]:
    """Read Infor's anonymous JSON resource, following its cookie-backed SSO assertion."""

    # Infor returns an empty 200 response to non-browser user-agent strings.
    # Keep the client identifier while using the browser-compatible prefix its
    # public Candidate Experience endpoint requires.
    headers = {"Accept": "application/json", "User-Agent": INFOR_USER_AGENT}
    for attempt in range(4):
        current_url = url
        redirect_count = 0
        retry = False
        while True:
            if (urlparse(current_url).hostname or "").lower() != expected_host.lower():
                raise SourceFetchError(f"Infor pagination left the public host for {url}")
            request = Request(current_url, headers=headers)
            try:
                with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
                    status = response.status
                    location = response.headers.get("Location")
                    decoded = response.read().decode("utf-8")
            except HTTPError as exc:
                status = exc.code
                location = exc.headers.get("Location")
                decoded = exc.read().decode("utf-8", "replace")
            except (URLError, TimeoutError) as exc:
                if attempt == 3:
                    raise SourceFetchError(f"Could not read Infor JSON from {url}: {exc}") from exc
                retry = True
                break

            if status in {301, 302, 303, 307, 308} and location:
                redirect_count += 1
                if redirect_count > 8:
                    raise SourceFetchError(f"Too many redirects from Infor JSON resource {url}")
                current_url = urljoin(current_url, location)
                continue
            if status == 429 or 500 <= status < 600:
                if attempt == 3:
                    raise SourceFetchError(f"HTTP {status} from Infor JSON resource {url}")
                retry = True
                break
            if not 200 <= status < 300:
                raise SourceFetchError(f"HTTP {status} from Infor JSON resource {url}")
            try:
                result = json.loads(decoded)
            except json.JSONDecodeError as exc:
                raise SourceFetchError(f"Expected JSON from Infor resource {url}") from exc
            if not isinstance(result, dict):
                raise SourceFetchError(f"Expected a JSON object from Infor resource {url}")
            return result

        if retry:
            time.sleep(min(2**attempt, 8))
    raise SourceFetchError(f"Could not read Infor JSON from {url}")


def _infor_value(item: dict[str, Any], field_name: str) -> Any:
    field = (item.get("fields") or {}).get(field_name)
    return field.get("value") if isinstance(field, dict) else None


def _infor_location(item: dict[str, Any]) -> str:
    parts = [
        str(_infor_value(item, f"LocationOfJob_prd_Location_ohb_{index}_chb_") or "").strip()
        for index in range(1, 5)
    ]
    parts = [part for part in parts if part]
    if len(parts) >= 3 and parts[0].upper() in {"US", "USA"}:
        city, state = parts[2].replace("_", " ").title(), parts[1].upper()
        extra = f" ({parts[3].replace('_', ' ').title()})" if len(parts) > 3 else ""
        return f"{city}, {state}{extra}"
    if parts:
        return ", ".join(part.replace("_", " ").title() for part in parts)
    raw = str(_infor_value(item, "LocationOfJob") or "").strip()
    return ", ".join(part.title() for part in raw.split(":") if part.strip())


def fetch_infor_cloudsuite(
    source: dict[str, Any],
    request_config: dict[str, Any],
    run_date: date,
) -> dict[str, Any]:
    """Fetch public Infor Candidate Experience listings using its JSON list resource."""

    endpoint = source["api_endpoint"]
    expected_host = urlparse(endpoint).hostname or ""
    organization = str(source["hr_organization"])
    job_board = str(source.get("job_board") or "EXTERNAL")
    params = {
        "pageop": "sort",
        "pagesize": max(1, int(request_config.get("page_size", 100))),
        "sortOrderName": str(request_config.get("sort_order_name", "JobPosting.ByPostDateBeginSet")),
        "isAscending": str(bool(request_config.get("sort_ascending", False))).lower(),
        "csk.JobBoard": job_board,
        "csk.showusingxi": "true",
        "csk.HROrganization": organization,
    }
    page_url = f"{endpoint}?{urlencode(params)}"
    jar = http.cookiejar.CookieJar()
    opener = build_opener(_NoRedirectHandler(), HTTPCookieProcessor(jar))
    pages: list[dict[str, Any]] = []
    postings: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    duplicate_items = 0

    for _ in range(MAX_PAGES):
        page = request_infor_json(page_url, opener, expected_host)
        pages.append(page)
        data_view = page.get("dataViewSet") or {}
        rows = data_view.get("data")
        if not isinstance(rows, list):
            raise SourceFetchError(f"Infor response did not contain a data list for {source['id']}")

        for item in rows:
            if not isinstance(item, dict):
                continue
            job_id = str(_infor_value(item, "JobRequisition") or _infor_value(item, "JobId") or "").strip()
            posting_number = str(_infor_value(item, "JobPosting") or "").strip()
            if not job_id or not posting_number:
                continue
            external_id = f"{job_id}:{posting_number}"
            unique_id = f"{source['id']}:{external_id}"
            if unique_id in seen_ids:
                duplicate_items += 1
                continue
            seen_ids.add(unique_id)

            posted_raw = str(
                _infor_value(item, "PostingDateRange_prd_Begin")
                or _infor_value(item, "PostingDateRange")
                or ""
            ).strip()
            if re.fullmatch(r"\d{8}", posted_raw):
                posted_raw = f"{posted_raw[:4]}-{posted_raw[4:6]}-{posted_raw[6:8]}"
            posting_route = f"JobPosting[JobPostingSet]({organization},{job_id},{posting_number}).JobPostingDisplay"
            posting_path = quote(posting_route, safe=",")
            posting_url = (
                f"{source['career_url'].rstrip('/')}/form/{posting_path}?"
                + urlencode(
                    {
                        "csk.JobBoard": job_board,
                        "csk.HROrganization": organization,
                        "csk.showusingxi": "true",
                    }
                )
            )
            category = (
                _infor_value(item, "CategoryDescriptionForSort")
                or _infor_value(item, "_op_Category_prd_Description_spc_translation_cp_")
                or _infor_value(item, "Category")
                or ""
            )
            postings.append(
                {
                    "posting_id": unique_id,
                    "external_id": external_id,
                    "title": str(_infor_value(item, "Description") or "").strip(),
                    "location": _infor_location(item),
                    "department": str(category).strip(),
                    "posted_date": parse_posted_date(posted_raw, run_date),
                    "posted_label": str(_infor_value(item, "_op_DisplayDuration_spc_translation_cp_") or "").strip(),
                    "url": posting_url,
                }
            )

        paging = data_view.get("pagingInfo") or {}
        has_next = paging.get("hasNext") is True
        if not has_next:
            break
        next_url = (data_view.get("pagingUrls") or {}).get("nextPageUrl")
        if not isinstance(next_url, str) or not next_url.strip():
            raise SourceFetchError(f"Infor response omitted the next-page URL for {source['id']}")
        page_url = urljoin(endpoint, next_url)
    else:
        raise SourceFetchError(f"Pagination safety limit reached for {source['id']}")

    warnings = [f"Skipped {duplicate_items} duplicate postings across pages"] if duplicate_items else []
    return {"postings": postings, "total": len(postings), "raw_pages": pages, "warnings": warnings}


def fetch_source(source: dict[str, Any], config: dict[str, Any], run_date: date) -> dict[str, Any]:
    api_type = source.get("api_type")
    if api_type == "oracle_candidate_experience":
        return fetch_oracle_candidate_experience(source, config.get("oracle_request", {}), run_date)
    if api_type == "successfactors_rss":
        return fetch_successfactors_rss(source)
    if api_type == "infor_cloudsuite":
        return fetch_infor_cloudsuite(source, config.get("infor_request", {}), run_date)
    if api_type == "workday_cxs" or source.get("ats", "").lower() == "workday":
        return fetch_workday(source, config.get("workday_request", {}), run_date)
    raise SourceFetchError(f"Unsupported public job-board adapter: {api_type or source.get('ats')} for {source['id']}")

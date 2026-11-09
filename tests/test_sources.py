from datetime import date
from urllib.parse import unquote, urlparse

from job_watcher.sources import fetch_oracle_candidate_experience, fetch_workday, parse_posted_date


def test_workday_paginates_by_returned_count_and_maps_postings(monkeypatch):
    calls = []
    pages = [
        {
            "total": 3,
            "jobPostings": [
                {"title": "Finance Intern", "externalPath": "/job/Tulsa-OK/Finance-Intern_R1", "locationsText": "Tulsa, OK", "postedOn": "Posted Today", "bulletFields": ["R1"]},
                {"title": "Staff Accountant", "externalPath": "/job/Bentonville-AR/Staff-Accountant_R2", "locationsText": "Bentonville, AR", "postedOn": "Posted Yesterday", "bulletFields": ["R2"]},
            ],
        },
        {
            "total": 3,
            "jobPostings": [
                {"title": "Tax Analyst", "externalPath": "/job/Tulsa-OK/Tax-Analyst_R3", "locationsText": "Tulsa, OK", "postedOn": "Posted 2 Days Ago", "bulletFields": ["R3"]}
            ],
        },
    ]

    def fake_request(url, body=None):
        calls.append((url, body))
        return pages[len(calls) - 1]

    monkeypatch.setattr("job_watcher.sources.request_json", fake_request)
    source = {
        "id": "sample",
        "employer": "Sample Co.",
        "ats": "Workday",
        "api_endpoint": "https://example.test/wday/cxs/sample/Sample/jobs",
        "career_url": "https://example.test/en-US/Sample",
    }
    result = fetch_workday(source, {"body_template": {"limit": 2, "offset": 0, "searchText": ""}}, date(2026, 11, 9))

    assert [body["offset"] for _, body in calls] == [0, 2]
    assert len(result["postings"]) == 3
    assert result["postings"][0]["posting_id"] == "sample:R1"
    assert result["postings"][0]["posted_date"] == "2026-11-09"
    assert result["postings"][1]["posted_date"] == "2026-11-08"
    assert result["postings"][0]["url"] == "https://example.test/en-US/Sample/job/Tulsa-OK/Finance-Intern_R1"


def test_workday_keeps_first_page_total_when_later_pages_report_zero(monkeypatch):
    calls = []

    def fake_request(url, body=None):
        calls.append(body["offset"])
        offset = body["offset"]
        if offset < 40:
            return {
                "total": 40 if offset == 0 else 0,
                "jobPostings": [
                    {"title": "Finance Analyst", "externalPath": f"/job/Tulsa-OK/Finance-Analyst_{offset + index}", "locationsText": "Tulsa, OK", "bulletFields": [str(offset + index)]}
                    for index in range(20)
                ],
            }
        return {"total": 0, "jobPostings": []}

    monkeypatch.setattr("job_watcher.sources.request_json", fake_request)
    source = {
        "id": "sample",
        "employer": "Sample Co.",
        "ats": "Workday",
        "api_endpoint": "https://example.test/wday/cxs/sample/Sample/jobs",
        "career_url": "https://example.test/en-US/Sample",
    }
    result = fetch_workday(source, {"body_template": {"limit": 20}}, date(2026, 11, 9))

    assert calls == [0, 20]
    assert len(result["postings"]) == 40
    assert result["total"] == 40


def test_workday_advances_past_overlapping_pages_until_unique_total(monkeypatch):
    calls = []
    pages = {
        0: {"total": 5, "jobPostings": [
            {"title": "Finance Analyst", "externalPath": f"/job/Tulsa-OK/Analyst_{key}", "bulletFields": [key]}
            for key in ("A", "B", "C")
        ]},
        3: {"total": 0, "jobPostings": [
            {"title": "Finance Analyst", "externalPath": f"/job/Tulsa-OK/Analyst_{key}", "bulletFields": [key]}
            for key in ("C", "D", "E")
        ]},
    }

    def fake_request(url, body=None):
        calls.append(body["offset"])
        return pages[body["offset"]]

    monkeypatch.setattr("job_watcher.sources.request_json", fake_request)
    source = {
        "id": "sample",
        "employer": "Sample Co.",
        "ats": "Workday",
        "api_endpoint": "https://example.test/wday/cxs/sample/Sample/jobs",
        "career_url": "https://example.test/en-US/Sample",
    }
    result = fetch_workday(source, {"body_template": {"limit": 3}}, date(2026, 11, 9))

    assert calls == [0, 3]
    assert len(result["postings"]) == 5
    assert result["total"] == 5
    assert result["warnings"] == ["Skipped 1 duplicate postings returned across overlapping pages"]


def test_workday_repeats_the_sweep_if_offset_drift_leaves_a_short_count(monkeypatch):
    calls = []
    pages = [
        {"total": 4, "jobPostings": [
            {"title": "Finance Analyst", "externalPath": f"/job/Tulsa-OK/Analyst_{key}", "bulletFields": [key]}
            for key in ("A", "B")
        ]},
        {"total": 0, "jobPostings": [
            {"title": "Finance Analyst", "externalPath": f"/job/Tulsa-OK/Analyst_{key}", "bulletFields": [key]}
            for key in ("B", "C")
        ]},
        {"total": 0, "jobPostings": []},
        {"total": 4, "jobPostings": [
            {"title": "Finance Analyst", "externalPath": f"/job/Tulsa-OK/Analyst_{key}", "bulletFields": [key]}
            for key in ("A", "B")
        ]},
        {"total": 0, "jobPostings": [
            {"title": "Finance Analyst", "externalPath": f"/job/Tulsa-OK/Analyst_{key}", "bulletFields": [key]}
            for key in ("C", "D")
        ]},
    ]

    def fake_request(url, body=None):
        calls.append(body["offset"])
        return pages[len(calls) - 1]

    monkeypatch.setattr("job_watcher.sources.request_json", fake_request)
    source = {
        "id": "sample",
        "employer": "Sample Co.",
        "ats": "Workday",
        "api_endpoint": "https://example.test/wday/cxs/sample/Sample/jobs",
        "career_url": "https://example.test/en-US/Sample",
    }
    result = fetch_workday(source, {"body_template": {"limit": 2}}, date(2026, 11, 9))

    assert calls == [0, 2, 3, 0, 2]
    assert len(result["postings"]) == 4
    assert result["total"] == 4
    assert result["warnings"][0].startswith("Repeated the board scan after 3 of 4 unique postings")


def test_workday_enriches_generic_multi_location_results(monkeypatch):
    requests = []
    page = {
        "total": 1,
        "jobPostings": [
            {"title": "Finance Analyst", "externalPath": "/job/Dallas-TX/Finance-Analyst_R1", "locationsText": "3 Locations", "postedOn": "Posted Today", "bulletFields": ["R1"]}
        ],
    }
    detail = {"jobPostingInfo": {"location": "Dallas, TX", "additionalLocations": ["Tulsa, OK", "Midland, TX"]}}

    def fake_request(url, body=None):
        requests.append(url)
        return page if body else detail

    monkeypatch.setattr("job_watcher.sources.request_json", fake_request)
    source = {
        "id": "sample",
        "employer": "Sample Co.",
        "ats": "Workday",
        "api_endpoint": "https://example.test/wday/cxs/sample/Sample/jobs",
        "career_url": "https://example.test/en-US/Sample",
    }
    result = fetch_workday(source, {"body_template": {"limit": 100}}, date(2026, 11, 9))

    assert len(requests) == 2
    assert result["postings"][0]["location"] == "Dallas, TX; Tulsa, OK; Midland, TX"
    assert len(result["raw_details"]) == 1


def test_oracle_candidate_experience_paginates_and_builds_job_links(monkeypatch):
    calls = []
    pages = [
        {
            "hasMore": True,
            "items": [{"TotalJobsCount": 2, "requisitionList": [{"Id": "101", "Title": "Finance Intern", "PostedDate": "2026-11-08", "PrimaryLocation": "Tulsa, OK, United States", "secondaryLocations": []}]}],
        },
        {
            "hasMore": False,
            "items": [{"TotalJobsCount": 2, "requisitionList": [{"Id": "102", "Title": "Revenue Auditor", "PostedDate": "2026-11-09", "PrimaryLocation": "Catoosa, OK, United States", "secondaryLocations": []}]}],
        },
    ]

    def fake_request(url, body=None):
        calls.append(url)
        return pages[len(calls) - 1]

    monkeypatch.setattr("job_watcher.sources.request_json", fake_request)
    source = {
        "id": "cherokee",
        "employer": "Cherokee Nation Businesses",
        "api_type": "oracle_candidate_experience",
        "site_number": "CX_1",
        "api_endpoint": "https://example.test/hcmRestApi/resources/latest/recruitingCEJobRequisitions",
        "career_url": "https://example.test/hcmUI/CandidateExperience/en/sites/CX_1",
    }
    result = fetch_oracle_candidate_experience(source, {"page_size": 1}, date(2026, 11, 9))

    query_first = unquote(urlparse(calls[0]).query)
    query_second = unquote(urlparse(calls[1]).query)
    assert "siteNumber=CX_1" in query_first
    assert "offset=0" in query_first
    assert "offset=1" in query_second
    assert len(result["postings"]) == 2
    assert result["postings"][1]["url"].endswith("/job/102")
    assert result["postings"][0]["posted_date"] == "2026-11-08"


def test_parse_posted_date_handles_relative_labels():
    assert parse_posted_date("Posted Today", date(2026, 11, 9)) == "2026-11-09"
    assert parse_posted_date("Posted 3 Days Ago", date(2026, 11, 9)) == "2026-11-06"

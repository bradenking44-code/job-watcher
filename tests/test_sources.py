from datetime import date
import json
from pathlib import Path
from urllib.parse import unquote, urlparse

from job_watcher.sources import (
    fetch_infor_cloudsuite,
    fetch_oracle_candidate_experience,
    fetch_successfactors_rss,
    fetch_workday,
    parse_posted_date,
)


COMMON_FIELDS = {"posting_id", "external_id", "title", "location", "department", "posted_date", "url"}


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
    assert COMMON_FIELDS <= result["postings"][0].keys()


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


def test_workday_keeps_complete_union_when_the_board_changes_during_repeat_scan(monkeypatch):
    calls = []
    pages = [
        {"total": 4, "jobPostings": [{"title": "Finance Analyst", "externalPath": f"/job/Tulsa-OK/Analyst_{key}"} for key in ("A", "B")]},
        {"total": 0, "jobPostings": [{"title": "Finance Analyst", "externalPath": f"/job/Tulsa-OK/Analyst_{key}"} for key in ("B", "C")]},
        {"total": 0, "jobPostings": [{"title": "Finance Analyst", "externalPath": "/job/Tulsa-OK/Analyst_C"}]},
        {"total": 0, "jobPostings": []},
        {"total": 4, "jobPostings": [{"title": "Finance Analyst", "externalPath": f"/job/Tulsa-OK/Analyst_{key}"} for key in ("A", "B")]},
        {"total": 0, "jobPostings": [{"title": "Finance Analyst", "externalPath": f"/job/Tulsa-OK/Analyst_{key}"} for key in ("B", "D")]},
        {"total": 0, "jobPostings": [{"title": "Finance Analyst", "externalPath": "/job/Tulsa-OK/Analyst_D"}]},
        {"total": 0, "jobPostings": []},
    ]

    def fake_request(_url, body=None):
        calls.append(body["offset"])
        return pages[len(calls) - 1]

    monkeypatch.setattr("job_watcher.sources.request_json", fake_request)
    source = {
        "id": "sample", "employer": "Sample Co.", "ats": "Workday",
        "api_endpoint": "https://example.test/wday/cxs/sample/Sample/jobs",
        "career_url": "https://example.test/en-US/Sample",
    }
    result = fetch_workday(source, {"body_template": {"limit": 2}}, date(2026, 11, 9))

    assert calls == [0, 2, 3, 4, 0, 2, 3, 4]
    assert len(result["postings"]) == result["total"] == 4
    assert any("Workday results changed during pagination" in warning for warning in result["warnings"])


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
    assert COMMON_FIELDS <= result["postings"][0].keys()


def test_oracle_continues_past_false_has_more_when_total_is_larger(monkeypatch):
    calls = []
    pages = [
        {"hasMore": False, "items": [{"TotalJobsCount": 2, "requisitionList": [{"Id": "101", "Title": "Finance Analyst", "PrimaryLocation": "Tulsa, OK"}]}]},
        {"hasMore": False, "items": [{"TotalJobsCount": 2, "requisitionList": [{"Id": "102", "Title": "Staff Accountant", "PrimaryLocation": "Tahlequah, OK"}]}]},
    ]

    def fake_request(url, body=None):
        calls.append(url)
        return pages[len(calls) - 1]

    monkeypatch.setattr("job_watcher.sources.request_json", fake_request)
    source = {
        "id": "cherokee",
        "employer": "Cherokee Nation Businesses",
        "api_type": "oracle_candidate_experience",
        "site_number": "CX_4001",
        "api_endpoint": "https://example.test/hcmRestApi/resources/latest/recruitingCEJobRequisitions",
        "career_url": "https://example.test/hcmUI/CandidateExperience/en/sites/CX_4001",
    }
    result = fetch_oracle_candidate_experience(source, {"page_size": 1}, date(2026, 11, 9))

    assert "offset=0" in unquote(urlparse(calls[0]).query)
    assert "offset=1" in unquote(urlparse(calls[1]).query)
    assert len(result["postings"]) == 2
    assert result["total"] == 2


def test_parse_posted_date_handles_relative_labels():
    assert parse_posted_date("Posted Today", date(2026, 11, 9)) == "2026-11-09"
    assert parse_posted_date("Posted 3 Days Ago", date(2026, 11, 9)) == "2026-11-06"


def test_successfactors_rss_maps_public_bok_postings(monkeypatch):
    xml = """<?xml version="1.0"?><rss><channel><item>
      <id>REQ-17</id><title>FP&amp;A Analyst (Tulsa, OK)</title>
      <location>Tulsa, OK</location><job_function>Finance &amp; Administration</job_function>
      <link>https://jobs.example.test/job/17</link>
    </item></channel></rss>"""
    monkeypatch.setattr("job_watcher.sources.request_text", lambda _url: xml)
    result = fetch_successfactors_rss({
        "id": "bok",
        "employer": "BOK Financial",
        "career_url": "https://jobs.example.test",
        "api_endpoint": "https://jobs.example.test/feed.xml",
    })

    posting = result["postings"][0]
    assert COMMON_FIELDS <= posting.keys()
    assert posting["posting_id"] == "bok:REQ-17"
    assert posting["title"] == "FP&A Analyst"
    assert posting["location"] == "Tulsa, OK"
    assert posting["url"] == "https://jobs.example.test/job/17"


def test_infor_maps_arvest_json_postings(monkeypatch):
    page = {
        "dataViewSet": {
            "data": [{
                "fields": {
                    "JobRequisition": {"value": "1001"},
                    "JobPosting": {"value": "2001"},
                    "Description": {"value": "Staff Accountant"},
                    "PostingDateRange_prd_Begin": {"value": "20261108"},
                    "CategoryDescriptionForSort": {"value": "Finance"},
                    "LocationOfJob_prd_Location_ohb_1_chb_": {"value": "US"},
                    "LocationOfJob_prd_Location_ohb_2_chb_": {"value": "AR"},
                    "LocationOfJob_prd_Location_ohb_3_chb_": {"value": "Bentonville"},
                }
            }],
            "pagingInfo": {"hasNext": False},
            "pagingUrls": {},
        }
    }
    monkeypatch.setattr("job_watcher.sources.request_infor_json", lambda *_args: page)
    source = {
        "id": "arvest",
        "employer": "Arvest Bank",
        "api_endpoint": "https://jobs.example.test/hcm/Jobs/list/JobPosting.SearchForJobsResults",
        "career_url": "https://jobs.example.test/hcm/Jobs",
        "hr_organization": "ARV",
        "job_board": "EXTERNAL",
    }
    result = fetch_infor_cloudsuite(source, {"page_size": 100}, date(2026, 11, 9))

    posting = result["postings"][0]
    assert COMMON_FIELDS <= posting.keys()
    assert posting["posting_id"] == "arvest:1001:2001"
    assert posting["title"] == "Staff Accountant"
    assert posting["location"] == "Bentonville, AR"
    assert posting["posted_date"] == "2026-11-08"
    assert posting["url"].startswith("https://jobs.example.test/hcm/Jobs/form/")


def test_configured_sources_use_supported_structured_adapters():
    config_path = Path(__file__).parents[1] / "config" / "sources.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    supported = {"Workday", "Oracle Cloud Recruiting", "SAP SuccessFactors Recruiting Marketing", "Infor CloudSuite HCM"}
    sources = config["sources"]

    assert len(sources) >= 15
    assert len({source["employer"] for source in sources}) >= 15
    assert all(source["ats"] in supported for source in sources)
    assert all(source.get("api_endpoint", "").startswith("https://") for source in sources)

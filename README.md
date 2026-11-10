# Job Watcher

A daily job-market tracker for finance students looking for finance and accounting jobs in the Tulsa, Oklahoma and Northwest Arkansas job markets. It collects public structured job-board feeds, rebuilds a posting history, reports daily changes, and publishes a small site with GitHub Pages.

**Published site:** [bradenking44-code.github.io/job-watcher](https://bradenking44-code.github.io/job-watcher/)

[![Tests](https://github.com/bradenking44-code/job-watcher/actions/workflows/tests.yml/badge.svg)](https://github.com/bradenking44-code/job-watcher/actions/workflows/tests.yml)

## Target roles and locations

The active watchlist covers 20 public job-board feeds across 19 employers. It includes employers whose own finance teams hire locally, banks with local finance and banking roles, and Cherokee Nation Businesses’ corporate and enterprise career boards. BOK Financial and Arvest Bank are now monitored alongside the other employers. The homepage has 20 monitored employer-board tiles. This is a practical starting set, not every employer in either region; additional boards can be added to `config/sources.json` as they are verified.

The title rule is intentionally broad and flags roles with finance, financial, FP&A, accounting, accounts payable or receivable, treasury, tax, audit, controller, credit, underwriting, investment, portfolio, wealth, banking, loan, budget, billing, payroll, or revenue-accounting language. It is a title-based screen, so flagged postings should be reviewed before applying.

Target markets:

- **Tulsa area:** Tulsa, Broken Arrow, Owasso, Jenks, Bixby, Sand Springs, Sapulpa, Catoosa, and Bartlesville as an outer-area extension.
- **Northwest Arkansas:** Bentonville, Fayetteville, Springdale, Rogers, Lowell, Siloam Springs, Bella Vista, Centerton, Cave Springs, and nearby communities.

Only listings whose job location matches one of these markets belong in the local results. A remote role is local only when the posting says candidates may work remotely from Oklahoma or Arkansas.

## Employer watchlist

The source registry contains the exact public structured-data endpoint for each active employer board and is the machine-readable source of truth. Workday and Oracle boards use JSON APIs. BOK Financial uses its public SuccessFactors RSS/XML feed, and Arvest uses the public JSON list resource from its Infor Candidate Experience board. Arvest's anonymous access flow does not require an account; the collector follows its cookie-backed assertion and paginates the JSON results. The collector does not parse job-board HTML. Cherokee Nation Businesses and ONE Gas use Oracle Candidate Experience; Cherokee Nation Businesses has separate corporate and enterprise career sites. Job counts change, so the pipeline paginates and records the result of each run.

| Market | Employer | Local coverage |
| --- | --- | --- |
| Tulsa | [ONEOK](https://oneok.wd1.myworkdayjobs.com/en-US/ONEOK) | Tulsa |
| Tulsa | [Williams](https://williams.wd5.myworkdayjobs.com/en-US/External) | Tulsa |
| Tulsa | [Helmerich & Payne](https://hpinc.wd5.myworkdayjobs.com/en-US/HPINC) | Tulsa |
| Tulsa | [AAON](https://aaon.wd108.myworkdayjobs.com/en-US/AAON) | Tulsa |
| Tulsa | [TD Williamson](https://tdwilliamson.wd1.myworkdayjobs.com/en-US/TDWCareers) | Tulsa |
| Tulsa and Northwest Arkansas | [Simmons Bank](https://simmonsbank.wd5.myworkdayjobs.com/en-US/SimmonsCareers) | Tulsa and regional Arkansas openings |
| Tulsa | [Airgas](https://airliquidehr.wd3.myworkdayjobs.com/en-US/AirgasExternalCareer) | Tulsa-area openings |
| Tulsa outer area | [ConocoPhillips](https://conocophillips.wd1.myworkdayjobs.com/en-US/External) | Bartlesville |
| Tulsa | [UMB Bank](https://umb.wd1.myworkdayjobs.com/en-US/UMBExternal) | Tulsa-area openings |
| Tulsa | [BOK Financial](https://jobs.bokf.com/go/) | Tulsa banking, finance, treasury, and early-career roles |
| Tulsa and Northwest Arkansas | [Arvest Bank](https://www.arvest.com/careers) | Oklahoma and Northwest Arkansas openings |
| Northwest Arkansas | [Walmart](https://walmart.wd504.myworkdayjobs.com/en-US/WalmartExternal) | Bentonville and nearby offices |
| Northwest Arkansas | [Tyson Foods](https://tysonfoods.wd5.myworkdayjobs.com/en-US/TSN1) | Springdale and nearby offices |
| Northwest Arkansas | [J.B. Hunt](https://jbhunt.wd501.myworkdayjobs.com/en-US/Careers) | Lowell and nearby offices |
| Northwest Arkansas | [University of Arkansas](https://uasys.wd5.myworkdayjobs.com/en-US/UAF_External_Career_Site) | Fayetteville |
| Northwest Arkansas | [George's Inc.](https://georgesinc.wd5.myworkdayjobs.com/en-US/JoinGeorges) | Springdale |
| Tulsa | [Ingredion](https://ingredion.wd1.myworkdayjobs.com/en-US/IngredionCareers) | Tulsa-area openings |
| Tulsa | [ONE Gas](https://ibedqy.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/ONEGas-Careers/jobs) | Tulsa |
| Tulsa and northeastern Oklahoma | [Cherokee Nation Businesses — corporate careers](https://ejvp.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/jobs) | Tulsa, Owasso, Tahlequah |
| Tulsa and northeastern Oklahoma | [Cherokee Nation Businesses — enterprise careers](https://ejvp.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_4001/jobs) | Catoosa, Claremore, Tahlequah, and other business locations |

The job boards can also return jobs outside the target cities. The location rule above applies across all sources, rather than assuming every job from a listed employer is local.

## Data and rebuild command

The daily collector saves compressed source responses under `data/raw/<UTC date>/<source>.json.gz`. `data/history.csv` is deterministically rebuilt from those raw snapshots and `data/status.json` describes the latest run. The first successful collection establishes a baseline; later runs open one dated GitHub issue when local finance postings are added or removed. Source failures are recorded and do not cause postings to be marked removed.

Run the collector manually:

```bash
python -m job_watcher.pipeline
```

The scheduled GitHub Actions workflow runs it daily in UTC, commits compressed snapshots and rebuilt history, and triggers a site refresh. Dates use UTC and history rows are sorted by `posting_id`.

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
pytest
```

## Repository files

| Path | Purpose |
| --- | --- |
| `.gitignore` | Excludes local environments, caches, and build output. |
| `.github/workflows/daily-pipeline.yml` | Daily collection, dated change issue, and data commit. |
| `.github/workflows/pages.yml` | Builds and publishes the static site with GitHub Pages. |
| `.github/workflows/tests.yml` | Runs pytest on pushes and pull requests. |
| `pyproject.toml` | Python project metadata and pytest configuration. |
| `README.md` | Project setup, target role and market, and operating instructions. |
| `config/sources.json` | Employer endpoints, target markets, and title terms. |
| `src/job_watcher/` | Python source adapters, pipeline, and history builder. |
| `tests/` | pytest coverage for source conversion and history rules. |
| `data/raw/` | Compressed JSON responses organized by UTC date. |
| `data/history.csv` | Canonical posting history. |
| `data/status.json` | Latest run summary and per-source results. |
| `.github/workflows/` | Daily pipeline, tests, and site publishing workflows. |
| `site/` | Today, Browse, and Markets pages plus installable, offline-capable web-app assets. |

## Project requirements

- Fetch all 20 active public feeds (19 JSON endpoints and one RSS/XML feed) anonymously, without parsing HTML.
- Keep each source response in raw data; apply the documented role and location rules when building local finance results.
- Continue when a source fails and record each source's result.
- Rebuild history deterministically from raw data, including first-seen, last-seen, and removed dates.
- Run the pipeline daily with GitHub Actions, open a dated issue for local finance job changes, and commit the raw, history, and status files.
- Publish Today, Browse, and Markets pages with GitHub Pages. The initial site includes offline support, a manifest, and a service worker.
- Run pytest on every push and show the test workflow badge here once it exists.

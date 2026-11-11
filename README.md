# Job Watcher

A daily job-market tracker for finance students looking for finance and accounting jobs in the Tulsa, Oklahoma and Northwest Arkansas job markets. It collects public applicant-tracking-system feeds, rebuilds a posting history, reports daily changes, and publishes a small site with GitHub Pages.

**Published site:** [bradenking44-code.github.io/job-watcher](https://bradenking44-code.github.io/job-watcher/)

[![Tests](https://github.com/bradenking44-code/job-watcher/actions/workflows/tests.yml/badge.svg)](https://github.com/bradenking44-code/job-watcher/actions/workflows/tests.yml)

## Target roles and locations

The active watchlist covers 20 public JSON job-board feeds across 19 employers. It includes employers whose own finance teams hire locally, banks with local finance and banking roles, and Cherokee Nation Businesses’ corporate and enterprise career boards. Regent Bank and Arvest Bank are monitored alongside the other employers. BOK Financial remains a supplemental careers link, with its previously collected postings retained as archived history. The homepage displays the 20 active boards and supplemental links. This is a practical starting set, not every employer in either region; additional boards can be added to `config/sources.json` after their public endpoints are verified.

The title rule is intentionally broad and flags roles with finance, financial, FP&A, accounting, accounts payable or receivable, treasury, tax, audit, controller, credit, underwriting, investment, portfolio, wealth, banking, loan, budget, billing, payroll, or revenue-accounting language. It is a title-based screen, so flagged postings should be reviewed before applying.

Target markets:

- **Tulsa area:** Tulsa, Broken Arrow, Owasso, Jenks, Bixby, Sand Springs, Sapulpa, Catoosa, Claremore, and Bartlesville as an outer-area extension.
- **Northwest Arkansas:** Bentonville, Fayetteville, Springdale, Tontitown, Rogers, Lowell, Siloam Springs, Bella Vista, Centerton, Cave Springs, and nearby communities.

Only listings whose job location matches one of these markets belong in the local results. A remote role is local only when the posting says candidates may work remotely from Oklahoma or Arkansas.

## Employer watchlist

The source registry contains the public endpoint and career-site URL for each active board. Workday, Oracle Candidate Experience, Greenhouse, and Arvest's Infor CloudSuite endpoints return JSON. Regent Bank uses Greenhouse's public Job Board API, which permits anonymous GET requests for published job data. BOK Financial's public SuccessFactors feed returns RSS/XML, so it is kept as a supplemental careers link rather than an active pipeline source; its original snapshots are kept under `data/archive/raw/`, and its historical postings are rebuilt to `data/archive/history.csv`. The required `data/history.csv` contains active-source rows with only open or removed statuses. Arvest's anonymous access flow does not require an account; the collector follows its cookie-backed assertion and paginates the JSON results. Cherokee Nation Businesses and ONE Gas use Oracle Candidate Experience; Cherokee Nation Businesses has separate corporate and enterprise career sites. Job counts change, so the pipeline paginates and records the result of each run. Workday boards can change while offset pages are being read; after a repeat scan, the collector keeps the distinct union when it meets the latest reported total and records a warning, instead of failing the whole board for a small count drift.

| Market | Employer | Applicant tracking system | Local coverage |
| --- | --- | --- | --- |
| Tulsa | [ONEOK](https://oneok.wd1.myworkdayjobs.com/en-US/ONEOK) | Workday JSON | Tulsa |
| Tulsa | [Williams](https://williams.wd5.myworkdayjobs.com/en-US/External) | Workday JSON | Tulsa |
| Tulsa | [Helmerich & Payne](https://hpinc.wd5.myworkdayjobs.com/en-US/HPINC) | Workday JSON | Tulsa |
| Tulsa | [AAON](https://aaon.wd108.myworkdayjobs.com/en-US/AAON) | Workday JSON | Tulsa |
| Tulsa | [TD Williamson](https://tdwilliamson.wd1.myworkdayjobs.com/en-US/TDWCareers) | Workday JSON | Tulsa |
| Tulsa and Northwest Arkansas | [Simmons Bank](https://simmonsbank.wd5.myworkdayjobs.com/en-US/SimmonsCareers) | Workday JSON | Tulsa and regional Arkansas openings |
| Tulsa | [Airgas](https://airliquidehr.wd3.myworkdayjobs.com/en-US/AirgasExternalCareer) | Workday JSON | Tulsa-area openings |
| Tulsa outer area | [ConocoPhillips](https://conocophillips.wd1.myworkdayjobs.com/en-US/External) | Workday JSON | Bartlesville |
| Tulsa | [UMB Bank](https://umb.wd1.myworkdayjobs.com/en-US/UMBExternal) | Workday JSON | Tulsa-area openings |
| Tulsa | [Regent Bank](https://job-boards.greenhouse.io/regentbank) | Greenhouse Job Board API JSON | Tulsa banking, credit, loan, and finance roles |
| Tulsa and Northwest Arkansas | [Arvest Bank](https://www.arvest.com/careers) | Infor CloudSuite JSON | Oklahoma and Northwest Arkansas openings |
| Northwest Arkansas | [Walmart](https://walmart.wd504.myworkdayjobs.com/en-US/WalmartExternal) | Workday JSON | Bentonville and nearby offices |
| Northwest Arkansas | [Tyson Foods](https://tysonfoods.wd5.myworkdayjobs.com/en-US/TSN1) | Workday JSON | Springdale and nearby offices |
| Northwest Arkansas | [J.B. Hunt](https://jbhunt.wd501.myworkdayjobs.com/en-US/Careers) | Workday JSON | Lowell and nearby offices |
| Northwest Arkansas | [University of Arkansas](https://uasys.wd5.myworkdayjobs.com/en-US/UAF_External_Career_Site) | Workday JSON | Fayetteville |
| Northwest Arkansas | [George's Inc.](https://georgesinc.wd5.myworkdayjobs.com/en-US/JoinGeorges) | Workday JSON | Springdale |
| Tulsa | [Ingredion](https://ingredion.wd1.myworkdayjobs.com/en-US/IngredionCareers) | Workday JSON | Tulsa-area openings |
| Tulsa | [ONE Gas](https://ibedqy.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/ONEGas-Careers/jobs) | Oracle Candidate Experience JSON | Tulsa |
| Tulsa and northeastern Oklahoma | [Cherokee Nation Businesses — corporate careers](https://ejvp.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/jobs) | Oracle Candidate Experience JSON | Tulsa, Owasso, Tahlequah |
| Tulsa and northeastern Oklahoma | [Cherokee Nation Businesses — enterprise careers](https://ejvp.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_4001/jobs) | Oracle Candidate Experience JSON | Catoosa, Claremore, Tahlequah, and other business locations |

The job boards can also return jobs outside the target cities. Raw snapshots preserve each successful board response, while the published history keeps only postings with a target-market location. For jobs offered in several cities, the history and site show only the matching Tulsa or Northwest Arkansas location segments. This rule applies across every source, rather than assuming every job from a listed employer is local.

BOK Financial remains available through its [careers page](https://jobs.bokf.com/go/) as a supplemental link. Its historical records are labeled **Archived source** because the public feed is RSS/XML and is no longer collected by the JSON-only pipeline.

## Data and rebuild command

The daily collector saves each successful active-source response in a compressed JSON snapshot under `data/raw/<UTC date>/<source>.json.gz`. Snapshots retain the board's full response; the published `data/history.csv` filters that data to locations in Tulsa or Northwest Arkansas and keeps only those local segments for multi-location postings. A failed source writes no raw snapshot; its status and error remain in `data/status.json`. The history build only uses successful active-source snapshots, so a failed source does not mark its local postings removed. Retired-source snapshots stay under `data/archive/raw/` and rebuild separately to `data/archive/history.csv`; they do not change the required open/removed history or open-job counts. A dated GitHub issue is opened every day, including days with no changes; reruns update that date's issue, and the next day's run closes it. The daily new count includes local postings that reappear after a successful run had removed them; the history keeps their original `first_seen` date and restores their open status.

Run the collector manually:

```bash
python -m job_watcher.pipeline
```

Rebuild the history from the saved raw files without making network requests:

```bash
python -m job_watcher.pipeline --build-only
```

The scheduled GitHub Actions workflow runs daily at 12:17 UTC (6:17 a.m. Central Standard Time or 7:17 a.m. Central Daylight Time), commits raw snapshots, history, status, and the daily change report, then dispatches the Pages workflow to publish the updated data. Dates use UTC, history rows are sorted by `posting_id`, and a date counts once even if the workflow is rerun.

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
| `.github/workflows/daily-pipeline.yml` | Daily collection, daily issue creation/update, previous-issue close, data commit, and Pages deployment dispatch. |
| `.github/workflows/pages.yml` | Builds and publishes the static site with GitHub Pages when dispatched or when site/data/config files change. |
| `.github/workflows/tests.yml` | Runs pytest on pushes and pull requests. |
| `pyproject.toml` | Python project metadata and pytest configuration. |
| `README.md` | Project setup, target role and market, and operating instructions. |
| `SUBMISSION.txt` | Four-line course submission with the student name, ID, repository, and live site. |
| `config/sources.json` | Active employer endpoints, supplemental careers links, archived source IDs, target markets, and title terms. |
| `src/job_watcher/__init__.py` | Marks the Python package. |
| `src/job_watcher/sources.py` | Anonymous Workday, Greenhouse, Oracle, and Infor JSON source adapters and field conversion. |
| `src/job_watcher/history.py` | Title/location matching, local-market filtering, and deterministic history rebuild from raw snapshots. |
| `src/job_watcher/pipeline.py` | Daily collection, raw snapshot saving, status, change report, and history build. |
| `tests/test_sources.py` | Adapter conversion, pagination, posting dates, and source registry checks. |
| `tests/test_history.py` | Title rule and first-seen, last-seen, removal, reappearance, and reproducibility checks. |
| `tests/test_pipeline.py` | Source failure handling, required status fields, and same-day rerun replacement. |
| `data/raw/` | Compressed JSON snapshots for successful active-source responses, organized by UTC date. |
| `data/archive/raw/` | Original compressed snapshots for retired sources, including the historical BOK feed payloads. |
| `data/history.csv` | Canonical posting history. |
| `data/archive/history.csv` | Retired-source postings, separate from the required open/removed history. |
| `data/status.json` | Latest run summary and per-source results. |
| `data/daily_changes.md` | The current dated report used as the body of the daily GitHub issue. |
| `data/raw/.gitkeep`, `site/.gitkeep`, `tests/.gitkeep`, `src/job_watcher/.gitkeep`, `.github/workflows/.gitkeep` | Keep required folders visible in Git when they contain no generated files. |
| `site/index.html` | Today page with run counts, latest changes, source status, and employer links. |
| `site/browse.html` | Searchable job list with role, employer, location, age, and status filters plus saved stars. |
| `site/market.html` | Local market summary and six history-based charts. |
| `site/assets/app.js` | Browser-side data loading, filters, shortlist storage, and report calculations; archived postings load separately from canonical history. |
| `site/assets/site.css` | Shared site colors, fonts, layout, and responsive styles. |
| `site/sw.js` | Cache-first fallback for offline pages and last-loaded data. |
| `site/manifest.webmanifest` | Installable web-app metadata. |
| `site/icon.svg` | App and site icon. |

## Project requirements

- Fetch active employer feeds anonymously as JSON, without parsing job-board HTML. BOK Financial remains a supplemental careers link; its prior source data is archived.
- Save successful responses, continue after a source failure, and record every board's success, count, and error in the status file.
- Rebuild all posting rows and dates deterministically from raw data, including first-seen, last-seen, and removed dates.
- Run daily with GitHub Actions, create/update a dated issue each day, close the previous day's issue, and commit raw, history, status, and change-report files.
- Publish Today, Browse, and Markets pages with the required filters, shortlist, six history charts, web-app manifest, and service worker.
- Run pytest on each push and pull request; the badge above links to the workflow.
- The course rubric also requires at least seven distinct run dates by the due date. That condition depends on elapsed days and cannot be supplied by a code change.

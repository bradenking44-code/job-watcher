# Job Watcher

A daily job-market tracker for finance students looking for finance and accounting jobs in the Tulsa, Oklahoma and Northwest Arkansas job markets. It will collect public job-board JSON, rebuild a posting history, report daily changes, and publish a small site with GitHub Pages.

## Target roles and locations

The active watchlist covers 15 employers with a public Workday JSON job-board endpoint. It includes employers whose own finance teams hire locally and banks with local finance and banking roles. Two more local financial employers, BOK Financial and Arvest Bank, are listed as discovery candidates while their public JSON endpoints are checked. This is a practical starting set, not every employer in either region; additional boards can be added to `config/sources.json` as they are verified.

The title rule is intentionally broad and flags roles with finance, financial, FP&A, accounting, accounts payable or receivable, treasury, tax, audit, controller, credit, underwriting, investment, portfolio, wealth, banking, loan, budget, billing, payroll, or revenue-accounting language. It is a title-based screen, so flagged postings should be reviewed before applying.

Target markets:

- **Tulsa area:** Tulsa, Broken Arrow, Owasso, Jenks, Bixby, Sand Springs, Sapulpa, Catoosa, and Bartlesville as an outer-area extension.
- **Northwest Arkansas:** Bentonville, Fayetteville, Springdale, Rogers, Lowell, Siloam Springs, Bella Vista, Centerton, Cave Springs, and nearby communities.

Only listings whose job location matches one of these markets belong in the local results. A remote role is local only when the posting says candidates may work remotely from Oklahoma or Arkansas.

## Employer watchlist

The source registry contains the exact public JSON endpoint for each employer and is the machine-readable source of truth. The endpoints were checked for unauthenticated access on 2026-11-09; each was returning fewer than 5,000 postings without a search term at that time. Job counts change, so the pipeline should paginate and record the result of each run.

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
| Northwest Arkansas | [Walmart](https://walmart.wd504.myworkdayjobs.com/en-US/WalmartExternal) | Bentonville and nearby offices |
| Northwest Arkansas | [Tyson Foods](https://tysonfoods.wd5.myworkdayjobs.com/en-US/TSN1) | Springdale and nearby offices |
| Northwest Arkansas | [J.B. Hunt](https://jbhunt.wd501.myworkdayjobs.com/en-US/Careers) | Lowell and nearby offices |
| Northwest Arkansas | [University of Arkansas](https://uasys.wd5.myworkdayjobs.com/en-US/UAF_External_Career_Site) | Fayetteville |
| Northwest Arkansas | [George's Inc.](https://georgesinc.wd5.myworkdayjobs.com/en-US/JoinGeorges) | Springdale |
| Tulsa | [Ingredion](https://ingredion.wd1.myworkdayjobs.com/en-US/IngredionCareers) | Tulsa-area openings |

The job boards can also return jobs outside the target cities. The location rule above applies across all sources, rather than assuming every job from a listed employer is local.

### Next sources to validate

- [BOK Financial](https://jobs.bokf.com/tulsa-jobs) has Tulsa banking, finance, treasury, and early-career roles.
- [Arvest Bank](https://www.arvest.com/careers) hires across Oklahoma and Arkansas, including Northwest Arkansas.

Their career pages are included in `config/sources.json`, but the boards are not active sources until an unauthenticated JSON endpoint is verified.

## Data and rebuild command

The pipeline will save compressed source responses under `data/raw/<UTC date>/<source>.json.gz`. `data/history.csv` is the reproducible posting history and `data/status.json` describes the latest run.

Planned history rebuild command (to be implemented):

```bash
python -m job_watcher.build_history --raw-dir data/raw --output data/history.csv
```

The history must be rebuilt from raw files alone. Dates use UTC and the history rows are sorted by `posting_id`.

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
| `pyproject.toml` | Python project metadata and pytest configuration. |
| `README.md` | Project setup, target role and market, and operating instructions. |
| `config/sources.json` | Employer endpoints, target markets, and title terms. |
| `src/job_watcher/` | Python source adapters, pipeline, and history builder. |
| `tests/` | pytest coverage for source conversion and history rules. |
| `data/raw/` | Compressed JSON responses organized by UTC date. |
| `data/history.csv` | Canonical posting history. |
| `data/status.json` | Latest run summary and per-source results. |
| `.github/workflows/` | Daily pipeline, tests, and site publishing workflows. |
| `site/` | Today, Browse, and Market pages plus installable web-app assets. |

## Project requirements

- Watch at least 15 employers through their ATS JSON endpoints without logging in or scraping HTML.
- Keep each source response in raw data; apply the documented role and location rules when building local finance results.
- Continue when a source fails and record each source's result.
- Rebuild history deterministically from raw data, including first-seen, last-seen, and removed dates.
- Run the pipeline daily with GitHub Actions, open a dated issue for changes, and commit the raw, history, and status files.
- Publish Today, Browse, and Market pages with GitHub Pages. Include offline support, a manifest, and a service worker.
- Run pytest on every push and show the test workflow badge here once it exists.

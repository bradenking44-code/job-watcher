# Job Watcher

A daily job-market tracker for the Financial Data Analytics project. It will collect public JSON job-board data, rebuild a posting history, report daily changes, and publish a small site with GitHub Pages.

This repository is scaffolding. The target role, employer list, title rule, source adapters, pipeline, site, tests, and workflows still need to be completed.

## Project decisions

- Target role and title rule: to be selected.
- Employers: at least 15; to be selected and checked for unauthenticated JSON endpoints.
- First-run date and due date: check Blackboard.
- Repository: public GitHub repository; configure GitHub Pages to deploy `site/` with a GitHub Actions workflow when the site is ready.

## Sources

No sources have been selected yet. Add one row per employer and document the applicant tracking system (ATS), JSON endpoint, and any search term used to keep a board under 5,000 postings.

| Employer | ATS | JSON endpoint | Search term |
| --- | --- | --- | --- |
| TBD | TBD | TBD | None |

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
| `README.md` | Project setup, source inventory, title rule, and operating instructions. |
| `src/job_watcher/` | Python source adapters, pipeline, and history builder. |
| `tests/` | pytest coverage for source conversion and history rules. |
| `data/raw/` | Compressed JSON responses organized by UTC date. |
| `data/history.csv` | Canonical posting history. |
| `data/status.json` | Latest run summary and per-source results. |
| `.github/workflows/` | Daily pipeline, tests, and site publishing workflows. |
| `site/` | Today, Browse, and Market pages plus installable web-app assets. |

## Project requirements

- Watch at least 15 employers through their ATS JSON endpoints without logging in or scraping HTML.
- Keep every posting returned by each source; apply a documented title rule to mark postings in the target role.
- Continue when a source fails and record each source's result.
- Rebuild history deterministically from raw data, including first-seen, last-seen, and removed dates.
- Run the pipeline daily with GitHub Actions, open a dated issue for changes, and commit the raw, history, and status files.
- Publish Today, Browse, and Market pages with GitHub Pages. Include offline support, a manifest, and a service worker.
- Run pytest on every push and show the test workflow badge here once it exists.

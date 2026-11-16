# Fitness Factory Class Finder

Find a group class across **all branches** of Fitness Factory (健身工廠) in one place, instead of checking each branch's timetable one by one.

> 可不分廠區找到目標課程：一次抓取所有廠區的團課課表，存進本機資料庫，再用條件篩選。

<!-- TODO: add a screenshot or GIF of the schedule view here (display.py). One image is worth more than any paragraph. -->

## Why I built it

The official site only shows one branch at a time. If I want a specific class (for example a 7 pm yoga class) I have to open dozens of branch pages. This tool collects every branch's weekly schedule, keeps it in SQLite, and lets me filter by class, time, instructor or branch.

## How it works

```
fitnessfactory.com.tw  ──►  scraper  ──►  pandas DataFrame  ──►  CSV + SQLite  ──►  schedule view
   (2 AJAX endpoints)      (httpx +        (cleaning and         (gym_schedule.db)    (display.py)
                            BeautifulSoup)  validation)
```

1. **Find the data source.** The timetable page is rendered from two AJAX endpoints (`filterCourse`, `filterSchedule`) that return JSON containing HTML fragments. Calling them directly with `httpx` is much lighter than driving a browser (no Playwright or Selenium needed).
2. **Handle the session token.** Every schedule request needs a fresh `XSRF-TOKEN`, so the scraper refreshes it through `filterCourse` before each `filterSchedule` call.
3. **Parse** the HTML fragments with BeautifulSoup into one row per class.
4. **Clean and validate** with pandas, then write a CSV and save to SQLite.
5. **Display** the data and remember your last filter (stored in the browser's localStorage).

## Details I had to solve

| Problem | How it is handled |
|---|---|
| The API returns weeks that cross a month (for example 6/29 to 7/5), so naive date parsing gives wrong months | Scan the seven day headers in order; when the day number goes down, move to the next month (and year) |
| Dates are in the ROC calendar (民國年) | Convert with year + 1911 |
| Substituted classes are only marked with a 🔺 in the class name | Detect the symbol, set `is_substitution = True`, and store the clean class name |
| Missing year or month in the API response | Fall back to the system date and print a warning instead of silently writing empty dates |
| Rows without a date would break the database (`NOT NULL`) | Filter them out before saving and report how many were dropped |
| One branch failing should not stop the run | Per-branch error handling, failed branches are listed at the end |
| Being polite to the site | Delay between branches (default 0.5 s), browser-like headers |

## Data columns

`store, date, weekday, start_time, end_time, course_name, instructor, room, is_substitution`

<!-- TODO: add a 3-row sample table from your real CSV. -->

## Project structure

| File | Purpose |
|---|---|
| `fitnessfactory_scraper.py` | Fetches and parses the schedule for all branches |
| `gym_db.py` | SQLite schema and saving (`init_db`, `save_schedule_to_db`) |
| `display.py` | Schedule view with filters |
| `debug.py` | Helper for checking a single branch |
| `gym_schedule.db` | Example data (SQLite) |
| `requirements.txt` | Dependencies |

## Quick start

```bash
git clone https://github.com/b06705039/fitness-factory-scraper.git
cd fitness-factory-scraper
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

python fitnessfactory_scraper.py     # scrape all branches, save CSV and SQLite
```

<!-- TODO: add the exact command that starts the display (display.py), and what the `env` command you added does. -->

Other modes (edit the bottom of `fitnessfactory_scraper.py`):

```python
df = scrape_all()                                          # all branches
df = scrape_all(target_stores=["台北信義", "台北內湖"])      # selected branches
df = scrape_all(date="2026-06-01")                         # a specific week
```

## Tech stack

Python 3 · httpx · BeautifulSoup4 · pandas · SQLite

## Limitations and notes

- Depends on the structure of the website; if the site changes, the parser needs updating.
- Only reads public timetable pages for personal use, with a delay between requests. Please be considerate if you reuse it.
- Not affiliated with Fitness Factory.

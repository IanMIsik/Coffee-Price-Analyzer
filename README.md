# Coffee Price Analyzer

Reads the Nairobi Coffee Exchange (NCE) weekly "Market Total" PDF reports and turns the AA / AB / C auction
averages into an estimated price for 50 kg of parchment and per kg of cherry. It checks the exchange every
30 minutes and updates when a new sale report appears.

## Run

```bash
py -3.13 -m pip install -r requirements.txt
py -3.13 -m uvicorn app.main:app --port 8100     # run from this folder
```

Open http://localhost:8100. Env vars: `PA_POLL_MINUTES` (default 30), `PA_DB` (database path).

## Deploy

See [DEPLOY.md](DEPLOY.md): on an Ubuntu server, `git clone` the repo and run `./deploy/setup.sh` (DuckDNS, HTTPS, login, auto-start, nightly update), plus manual
options. A `Dockerfile` and `docker-compose.yml` are included: `docker compose up -d` serves the app on
http://localhost:8100.

## Method

1. Mix price = simple average of the AA, AB and C average prices (USD per 50 kg of clean coffee).
2. × USD/KES rate = KES per 50 kg clean; ÷ 50 = KES per kg clean.
3. Per kg parchment = green yield (default 0.80) × KES per kg clean × (1 − deductions %) − processing cost.
4. 50 kg parchment = 50 × per kg parchment. Cherry per kg = per kg parchment ÷ cherry ratio (default 5.5).

The defaults (exchange rate, yield, ratio, deductions) are placeholders. Set yours on the dashboard.

## Data coverage

Three sources, in priority order when they describe the same sale:

1. **Hand-entered** (`data/manual_sales.json`): for reports the parser cannot read. Sale 39 of 2025/26 is an image-only
   PDF, so it was transcribed by eye. Add entries there for any other report or paper record.
2. **Exchange reports** (nairobicoffeeexchange.co.ke/market-reports): sales 23 onwards of 2025/26 (March 2026). Sale 28
   is not published. Full AA/AB/C averages and bag counts.
3. **News write-ups** (Kilimo News, via its public WordPress API): older sales back to July 2025. These are prose, so
   only numbers are extracted: the overall market average (nearly always) and AA/AB/C averages (sometimes).
   Sales without all three grades are **estimated**: market average ÷ the usual ratio of market average to AA/AB/C mix,
   measured from the exchange's own reports (about 0.93 in the main season, 0.81 late in the season). Estimated points
   are shown hollow on the chart and labelled in the tables. Checked against the exchange's 2026 reports, the news
   market averages were within about 1% on average (worst case 2%), so estimates are good to roughly ±2%.

Sale numbers restart each October, so sales are keyed by season and number (e.g. 2025/26 #30 vs 2024/25 #30).
The news pass runs at startup and every 12 hours (`PA_NEWS_HOURS`); the exchange is checked every 30 minutes.

## Tests

```bash
py -3.13 -m pytest -q
```

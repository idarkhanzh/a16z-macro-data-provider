# BLS macro release bot

Sends US macro releases (CPI, jobs, wages, PPI, JOLTS, ECI, import/export prices,
productivity, real earnings) to Telegram within seconds of the official BLS release.
It is a single always-on Python worker: no web server, no database, no files.

```
US CPI — September 2026
Headline: +0.6% m/m | 3.7% y/y  (prev +0.4% | 3.4%)
Core: +0.3% m/m | 2.6% y/y  (prev +0.3% | 2.4%)
```

## Environment variables

| Variable | Required | Example | Notes |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | yes | `123456789:AA...` | From [@BotFather](https://t.me/BotFather). |
| `TELEGRAM_CHAT_IDS` | yes | `123456789,-1001234567890` | Comma-separated. Private chats, groups, and channels/supergroups (`-100...`). Whitespace is trimmed. |
| `BLS_API_KEY` | yes | `0123abcd...` | BLS Public Data API v2 key ([register](https://data.bls.gov/registrationEngine/)). |
| `LOG_LEVEL` | no | `INFO` | `DEBUG` logs every poll. |

The bot exits with a clear error if a required variable is missing. Secrets are never
logged; any log line that contains one has it replaced with `***`.

For channels, add the bot as an administrator. For groups, add the bot to the group.
To find a chat ID, send the bot a message and open
`https://api.telegram.org/bot<token>/getUpdates`, or forward a message to a bot such as @userinfobot.

## Deploy on Railway

1. Push this repo to GitHub.
2. In Railway, choose **New Project → Deploy from GitHub repo** and pick the repo.
3. Under the service's **Variables**, add `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_IDS` and `BLS_API_KEY`.
4. Deploy. `railway.json` sets the start command (`python -m macro_bot`), restart on
   failure, and one replica. Python 3.12 comes from `.python-version`. Do not generate a
   public domain: the bot opens no port.
5. Check the deploy logs for `baseline ... (not sent)` lines, one per release.

**Keep replicas at 1.** Each replica polls and sends on its own, so two replicas send
every message twice. `railway.json` sets `numReplicas: 1` and `overlapSeconds: 0`, so
old and new deployments don't run at the same time.

Avoid deploying between 08:29 and 08:45 ET, or between 09:59 and 10:15 ET. A restart
records BLS's current data as already seen, so a release that lands during the restart
is not sent.

## Run locally

```bash
python -m pip install -r requirements-dev.txt
```

Copy `.env.example` to `.env` and fill it in. Real environment variables take precedence over `.env`.

```bash
python -m macro_bot --dry-run
```

`--dry-run` fetches the latest data and prints every message without sending. It needs only `BLS_API_KEY`.

```bash
python -m macro_bot --test-send
```

`--test-send` sends one test message to every chat ID and prints OK or FAILED for each. It needs only the Telegram variables.

```bash
python -m pytest
```

## How it works

- **Schedule.** Everything runs in-process in `America/New_York` time via `zoneinfo`, so
  daylight saving is automatic. On weekdays, polling starts 15 s before 08:30 and before
  10:00. It polls every 2 s until 2 minutes after the release time, then every 15 s
  until 15 minutes after. A catch-up poll also runs every 30 minutes from 07:00 to
  18:00 for releases at unusual times. Each poll is one batched BLS request for all
  series (up to 50 per request).
- **Query budget.** That schedule uses about 263 of the 500 daily BLS queries. The bot
  counts queries per ET day. From 85% of the limit, it spaces queries at least 60 s
  apart. From 98%, or when BLS reports the threshold, it pauses until the next day.
- **New data.** A release counts as new when its headline series' latest period
  (year + month or quarter) is newer than the one in memory. Value changes alone,
  such as revisions, never trigger a message. At startup, the bot records the latest
  period of every series without sending.
- **One message per release.** All of a release's series go into one message. If the
  headline is new but another of its series hasn't updated yet, the bot re-polls every
  3 s for up to 30 s. After that, it sends anyway and shows `n/a` for the missing values.
- **Delivery.** Each chat is sent to independently and in the background, so one failing chat never
  blocks the others or the next poll. HTTP 429 waits Telegram's `retry_after`. Network
  errors and 5xx retry with backoff, up to 5 attempts. If a group was upgraded to a
  supergroup, the bot follows the new ID and logs a reminder to update `TELEGRAM_CHAT_IDS`.
- **Calculations.** Percent changes are computed from index levels with exact decimal
  arithmetic, rounded half-up to one decimal, as in the BLS tables. If a base period is
  missing, the value shows `n/a`. For example, BLS never collected October 2025 CPI data
  because of the 2025 shutdown.

Second estimates for the same period, such as revised Productivity and Costs for a quarter
already sent, are not sent again, because the period is not new.

## Indicators

| Release | Usual time (ET) | Headline series | Shown |
|---|---|---|---|
| CPI | 08:30 | `CUSR0000SA0` | All items and core (ex food & energy): m/m from SA `CUSR0000SA0`/`CUSR0000SA0L1E`, y/y from NSA `CUUR0000SA0`/`CUUR0000SA0L1E` |
| Real Earnings | 08:30 (with CPI) | `CES0500000013` | Real avg hourly (`CES0500000013`) and weekly (`CES0500000012`) earnings, m/m and y/y |
| Employment Situation | 08:30 | `CES0000000001` | Payroll change in thousands plus the prior two months; unemployment rate `LNS14000000`; AHE `CES0500000003` m/m and y/y |
| PPI | 08:30 | `WPSFD4` | Final demand (`WPSFD4` m/m, `WPUFD4` y/y); core ex food, energy, trade (`WPSFD49116`/`WPUFD49116`); ex food & energy (`WPSFD49104`/`WPUFD49104`) |
| JOLTS | 10:00 | `JTS000000000000000JOL` | Job openings, hires, quits, layoffs (levels, millions) |
| Employment Cost Index | 08:30, quarterly | `CIS1010000000000I` | Compensation and wages & salaries, civilian: q/q from SA index, y/y from NSA index |
| Import/Export Prices | 08:30 | `EIUIR` | Imports, imports ex fuel (`EIUIREXFUELS`), exports (`EIUIQ`): m/m and y/y (NSA) |
| Productivity and Costs | 08:30, quarterly | `PRS85006093` | Nonfarm business productivity and unit labor costs (`PRS85006113`) indexes: q/q annualized and y/y |

Every series ID was checked against the live BLS API and its official title on
data.bls.gov. For CPI, PPI, jobs, real earnings, JOLTS and import/export prices, the
computed figures were checked against the latest BLS news releases. For ECI and
productivity, they were checked against BLS's own percent-change series for every
quarter since 2017. The tests pin these checks to a real API response captured on
2026-10-16 (`tests/fixtures`).

## Add or change an indicator

All indicators live in [`macro_bot/config.py`](macro_bot/config.py). A release is a
title, a headline series and lines of fields:

```python
Release(
    key="cpi_shelter",                # unique id, used in logs
    title="US CPI Shelter",
    headline="CUSR0000SAH1",          # a new period here triggers the message
    lines=(
        line("Shelter", mom("CUSR0000SAH1"), yoy("CUUR0000SAH1")),
    ),
),
```

Field helpers:

| Helper | Shows |
|---|---|
| `mom(id)` | `+0.3% m/m` |
| `qoq(id)` | `+0.9% q/q` |
| `qoq_annualized(id)` | `+1.4% q/q ann.` |
| `yoy(id)` | `2.9% y/y` |
| `change(id, suffix="K")` | `+29K` |
| `level(id, decimals, scale, suffix)` | `4.2%`, `7.08M` |

`line(..., prev=2)` shows two earlier periods; `prev=0` hides them.

Look up a series ID with the [BLS data finder](https://data.bls.gov/dataQuery/search),
confirm it with `https://data.bls.gov/timeseries/<ID>`, then run `--dry-run` to see the
message. A release time other than 08:30 or 10:00 ET goes in `SCHEDULE.release_times`.
Keep the total under 50 series to stay at one request per poll; past 50, the bot
splits the poll into extra requests, and each one counts against the daily limit.

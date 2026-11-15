# InvestTrack

[![CI](https://github.com/samuel-mendes-monteiro/InvestTrack/actions/workflows/ci.yml/badge.svg)](https://github.com/samuel-mendes-monteiro/InvestTrack/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12%20%7C%203.14-blue)
![TypeScript](https://img.shields.io/badge/react-TypeScript-blue)
![Coverage](https://img.shields.io/badge/coverage-98%25-brightgreen)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Website](https://img.shields.io/badge/site-investtrack.online-0969da)](https://investtrack.online)

> A personal investment portfolio tracker for the Brazilian stock market (B3), with live quotes and exact average-cost and profit calculations.

### 🌐 Try it at [investtrack.online](https://investtrack.online)

Create an account, import your B3 statement and see your portfolio, also on your phone. It runs on free plans, so the first visit after a quiet while takes up to a minute to wake the server.

![Carteira: net worth, totals, cumulative return against CDI and Ibovespa, and the allocation](docs/portfolio.jpg)

## The problem

People who invest through more than one broker don't get a single view of their portfolio. Each broker's app shows its own account only. Spreadsheets take effort, break easily and rarely calculate the **average cost** and **returns** correctly.

## The solution

InvestTrack is a web app where each person, with their own account, records their buy and sell trades and gets back:

- your current position in each asset
- the average cost (*preço médio*), including fees, adjusted automatically for stock splits, reverse splits and bonus shares
- realized and unrealized profit/loss, in R$ and in %
- dividends, JCP and FII distributions, **computed automatically** from what B3 publishes and what you owned on each record date, including income still to be paid
- how your portfolio is split across assets
- fixed income (CDB, LCI, LCA) at % of CDI, pre-fixed or IPCA+, valued daily with IOF and regressive income tax, with partial redemptions
- trades imported from **B3's trade statement** (Excel), with a preview and without duplicates
- your **time-weighted return** since the first trade or over the last 7 days, month, 6 months or year, compared with the CDI and the Ibovespa, split into what came from **prices** and what came from **income**, with a switch to leave income out
- your **net worth over time** and the **gain** in each period: how much it grew beyond the money you put in, fees included
- a price suggested as you type a trade: the current quote for today, or B3's official close for an earlier day

![Rentabilidade: return split into prices and income, with the income switch](docs/performance.jpg)

A new account is greeted with the ways to start (importing the statement, with a [step-by-step guide](web/src/help/ImportGuidePage.tsx), a first buy, or fixed income), and the profile page changes the password or deletes the account with all of its data. Visitors see a product page before the login.

Quotes from B3 are fetched automatically from [brapi.dev](https://brapi.dev), and income events from B3's own website. Invalid operations, such as selling more shares than you own on that date, are refused with a clear message:

![Selling more than owned is refused](docs/validation.jpg)

## Core design principle

**The trade history is the single source of truth.**

Positions (quantity, average cost) are **never stored** in the database. They are always **recalculated** from the list of trades. Editing or deleting an old trade therefore updates everything automatically, and the data can never become inconsistent.

## Architecture

```mermaid
flowchart LR
    UI["<b>Frontend</b><br/>React + TypeScript"] -- "HTTP / JSON" --> API["<b>API</b><br/>FastAPI"]
    API -. "OpenAPI schema" .-> UI
    API --> Core["<b>Calculation core</b><br/>pure Python, no I/O"]
    API --> Repo["<b>Repository</b><br/>SQLAlchemy"]
    Repo --> DB[("SQLite / PostgreSQL")]
    API --> Prices["<b>Price cache</b><br/>15 min, fallback"]
    Prices -- "HTTPS + token" --> Brapi["brapi.dev"]
    Prices --> DB
    API --> Events["<b>Corporate events</b><br/>daily sync, kept forever"]
    Events -- "HTTPS" --> B3["B3 website"]
    Events --> DB
    API --> Market["<b>Market history</b><br/>background download"]
    Market -- "COTAHIST files" --> B3
    Market -- "SGS API" --> BCB["Central Bank (CDI, IPCA)"]
    Market --> DB
```

The backend is split into layers, and imports only point downwards: `core` uses nothing else from the project, `sources` turn outside data into `core`'s types, `storage` uses both, and `api` uses everything. The calculation rules therefore run, and are tested, without a database or a network. [`tests/test_architecture.py`](tests/test_architecture.py) fails on an import in the wrong direction.

| Layer | Module | Responsibility |
|---|---|---|
| **api** | [`api/app.py`](investtrack/api/app.py) | Builds the app: data sources on `app.state`, routers under `/api`, the built web app on every other path |
| | [`api/routes/`](investtrack/api/routes) | One router per resource (`auth`, `operations`, `income`, `portfolio`, `fixed_income`, `imports`, `performance`). Thin: JSON in, repository call, errors to status codes |
| | [`api/deps.py`](investtrack/api/deps.py) | Dependencies: database session, logged-in user from the session cookie, data sources, uploaded file |
| | [`api/errors.py`](investtrack/api/errors.py) | Domain errors as HTTP errors with stable codes and their extra fields |
| | [`api/schemas.py`](investtrack/api/schemas.py) | Request and response models (Pydantic); money as strings |
| | [`api/views.py`](investtrack/api/views.py) | Domain objects into responses, and the reads several routes share |
| **core** | [`core/portfolio.py`](investtrack/core/portfolio.py) | Average cost, realized and unrealized profit, stock events. Pure functions: no database, no HTTP |
| | [`core/income.py`](investtrack/core/income.py) | Income (dividends, JCP, FII distributions): computed from events and trades, monthly totals |
| | [`core/performance.py`](investtrack/core/performance.py) | Time-weighted return and benchmarks (CDI, Ibovespa) |
| | [`core/fixed_income.py`](investtrack/core/fixed_income.py) | CDB, LCI and LCA: value from the CDI, a fixed rate or IPCA+, IOF and income tax |
| | [`core/statement_import.py`](investtrack/core/statement_import.py) | Decides which statement rows are new, already registered or invalid |
| **sources** | [`sources/b3.py`](investtrack/sources/b3.py) | The only module that knows B3's corporate events URLs and JSON format |
| | [`sources/b3_statement.py`](investtrack/sources/b3_statement.py) | Reads B3's trade statement (Excel); the only module that knows its format |
| | [`sources/brapi.py`](investtrack/sources/brapi.py) | The only module that knows brapi's URL and JSON format |
| | [`sources/history.py`](investtrack/sources/history.py) | Clients and parsers for COTAHIST files, the Ibovespa table and the CDI and IPCA series |
| **storage** | [`storage/models.py`](investtrack/storage/models.py), [`db.py`](investtrack/storage/db.py) | Tables (SQLAlchemy), exact decimals on SQLite and PostgreSQL, engine and migrations on startup |
| | [`storage/repository.py`](investtrack/storage/repository.py) | Saves and reads each user's data; validates every change through the calculation core |
| | [`storage/events.py`](investtrack/storage/events.py) | Stores B3 events (income, splits, bonus shares), synced once a day, with fallback to what is stored |
| | [`storage/market_data.py`](investtrack/storage/market_data.py) | Stores daily prices, Ibovespa, CDI and IPCA; downloads only what is missing, in the background |
| | [`storage/prices.py`](investtrack/storage/prices.py) | Quote cache with fallback to the last known price |
| | [`storage/migrations/`](investtrack/storage/migrations) | Alembic migrations, applied automatically when the API starts |
| **top level** | [`auth.py`](investtrack/auth.py) | Accounts, Argon2id password hashes, session tokens and the login limit |
| | [`openapi.py`](investtrack/openapi.py) | Exports the API's OpenAPI schema, which the frontend's types are generated from |
| **web** | [`web/src/api/`](web/src/api) | Typed API client: session, error codes translated into Portuguese, one hook per endpoint |
| | [`web/src/format.ts`](web/src/format.ts) | Brazilian formatting of the API's decimal strings, exact (BigInt), never through a float |
| | [`web/src/`](web/src) | One folder per screen: `portfolio` (Carteira, with the fixed income card), `networth` (Patrimônio), `performance` (Rentabilidade), `income`, `operations`, `profile`, `landing`, `help` |

## Calculation rules

**Buy:** the average cost is recalculated, and fees are added to the cost.

```
new_avg = (current_qty × current_avg + bought_qty × price + fees) / (current_qty + bought_qty)
```

**Sell:** the average cost **does not change**. The difference becomes realized profit (or loss).

```
realized_profit += sold_qty × (sell_price − avg) − fees
```

Trades are processed **in date order** (not in the order they were entered), and a sale can never leave a negative quantity. Selling a whole position resets the average cost, so a later purchase starts fresh.

**Splits, reverse splits and bonus shares** (*desdobramentos*, *grupamentos*, *bonificações*) are applied at the end of their record date, after that day's trades:

```
new_qty = floor(qty × multiplier)        e.g. 1:2 split → × 2, 10:1 reverse split → × 0.1
new_avg = total_cost / (qty × multiplier)
```

- Splits and reverse splits **don't change the total cost**: 100 shares at R$ 30 become 200 at R$ 15.
- Fractions are dropped, because B3 sells them in an auction and pays the holder in cash. Their share of the cost leaves with them, so the average price is the same as without rounding. The auction cash is not tracked.
- Bonus shares enter with the **cost attributed by the company** (*custo atribuído*), which raises the total cost. B3 doesn't publish this value in its data (it is only in each company's notice to shareholders), so it is typed once per bonus event; until then the new shares count at zero cost and the UI warns about it.

**Income (*proventos*)** is computed, never typed, just like positions:

```
gross = shares held at the end of the record date (data com) × value per share
net   = gross − tax withheld   (15% on JCP; dividends and FII distributions: none)
```

- Owning the shares at the **end of the record date** gives the right, even if they are sold before the payment. A purchase on the record date itself counts.
- Income **does not change the average cost**, following Brazilian tax rules. It is tracked as a separate result.
- Announced income with a future payment date is shown as **pending** and not counted as received yet.
- Since it is recalculated from the trades, fixing an old trade fixes the income too.
- For what B3 doesn't publish (BDRs, income older than the history B3 shows), income can be entered manually, as the total shown in the broker statement.

**Fixed income** has no market price: its value comes from a formula, using the CDI already downloaded for the benchmarks and the IPCA from the Central Bank (SGS series 433).

```
% of CDI:   value = amount × Π (1 + CDI_day × percentage)      (each business day)
pre-fixed:  value = amount × (1 + annual_rate) ^ (business_days / 252)
IPCA+:      value = pre-fixed value × IPCA accumulated since the start
```

- Business days come from the CDI series itself: the Central Bank publishes a rate only on business days, so it doubles as the official calendar.
- If redeemed today, a CDB pays IOF on the gain within 30 days (96% on day 1 down to 0% on day 30) and income tax on the rest of the gain: 22.5% up to 180 days, 20% up to 360, 17.5% up to 720 and 15% after that. LCI and LCA are tax exempt.
- Applying is an inflow and redeeming an outflow, so fixed income joins the portfolio's value and its TWR. An LCI at 100% of the CDI earns exactly the CDI.
- For IPCA+, each month's IPCA is spread over its calendar days. A month's IPCA only comes out around the 10th of the next one; until then the last published month is repeated and the value is flagged as an estimate. (Banks and the Tesouro use an anniversary date and business days; over whole months the result is the same.)
- An investment applied after the last business day with a published CDI (today, or on a weekend) is worth exactly what was applied: no day has passed to earn anything or to owe tax.
- Investments can be edited after the fact; their redemption and partial redemptions stay, and an edit they would no longer fit (a smaller amount than what was withdrawn, say) is refused.
- **Partial redemptions** keep the rest running. Since the value grows in proportion to the money invested, withdrawing R from a value V leaves (1 − R/V) of everything, principal included. Each withdrawal pays tax on its own share of the gain, at the rate for the days since the start. A withdrawal must be smaller than the value on that day (taking everything is the full redemption) and on a business day with a known value.

**Importing B3's trade statement** (Área do Investidor → Extratos → Negociação, in Excel) shows a preview first. Each row is:

- **new**, to be added;
- **already registered**: an operation with the same date, type, ticker, quantity and price exists, imported before or typed by hand (fees don't count: the statement has none). The comparison is between multisets, so two identical trades on the same day are two trades, and overlapping statements import each trade once;
- **rejected**, if that ticker's trades would sell more than owned: its new rows stay out, since half a history gives an average price that matches nothing;
- **skipped**, for options, forward and futures markets.

Fractional-lot tickers become the regular ones (`RECV3F` is `RECV3`). Imported trades have no fees, because the statement doesn't have them.

**Performance** is the time-weighted return (TWR), which measures how the assets did regardless of when money was put in or taken out:

```
daily_return = (value_at_close + income_paid − net_flow) / previous_value − 1
TWR          = (1 + r₁) × (1 + r₂) × … − 1
```

- Buys are inflows and sells are outflows (fees included), assumed at the end of the day: a buy's first day counts from the trade price to the close. Putting in ten times more money doesn't change the return.
- Income counts as return, net of withheld tax.
- Shares are valued at the official close of each day. A day without trades in an asset uses its last close.
- The CDI is accumulated over the same days (each day's rate is earned overnight), and the Ibovespa from the close before the first trade.
- The same TWR is also computed **without income**. That is the part that came from prices (and fees); for a single purchase it equals the position's result. The screen shows both as two parts that add up to the total, `Cotação +7,07% · Proventos +2,01%`, and a switch moves the chart to the price-only line.
- A period (7D, 1M, 6M, 1A) is measured from the last close on or before its start: every series is rebased there, `(1 + R_end) / (1 + R_base) − 1`, which is exact for chained returns. 7 days are calendar days, so on a Friday it starts from the Friday before.

**Net worth and gain.** The net worth chart shows, at each close, the stocks at that close plus fixed income **net** of taxes (the same number as the Patrimônio card), and a last point for **now**, with live quotes, so a sale or redemption made today shows at once. Its headline is the gain, not the change:

```
money_in = buys (with fees) − sales (net of fees) + fixed income applied − redeemed
gain     = (net_worth_end − net_worth_start) − (money_in_end − money_in_start)
```

Over the whole history it starts from nothing, so the first purchase, fees included, counts as money put in: buying at R$ 1,966.00 plus R$ 7.90 of fees and being worth R$ 2,113.50 is a gain of R$ 139.60, the same as the position's result, not R$ 147.50. Income paid out leaves the portfolio as cash, so it is not part of this gain (it is part of the return above).

## Technical decisions

- **No `float` for money.** `Decimal` everywhere, because `0.1 + 0.2 != 0.3` in floating point. This is enforced, not just a convention: the core rejects floats, JSON numbers from brapi and from clients are parsed straight into `Decimal`, and money is typed into text fields (accepting `30,50` or `1.234,56`), not number inputs, which give the browser's float.
- **Decimals are stored as text on SQLite.** SQLite has no real decimal type, so SQLAlchemy would silently store `Numeric` as a float. A custom column type keeps exact values on SQLite and uses native `NUMERIC` on PostgreSQL, without a precision or scale: `NUMERIC(20, 8)` would round a price with 9 decimal places or a 1/3 reverse split factor.
- **Rounding happens only for display.** Calculations keep full precision; the API rounds to 2 decimals only in the response, and sends money as JSON strings (`"35.10"`) so clients never turn it into a float.
- **Calculations are isolated** in a pure module that takes a list of trades and returns positions. The repository reuses it to validate changes: adding a sale, or deleting a purchase that a later sale depends on, is refused before anything is saved.
- **Errors have stable codes.** The API returns `{"code": "INSUFFICIENT_POSITION", "ticker": ..., "available": ...}`; the frontend translates codes into Portuguese. The backend stays language-neutral.
- **Quotes are cached** in the database for 15 minutes per ticker, so the cache survives restarts and stays within brapi's free quota. If brapi is down, the last known price is shown, flagged as stale, together with when it was fetched.
- **Outages vs. per-ticker errors.** A timeout or 5xx pauses calls to brapi for a minute, so a portfolio with many tickers doesn't wait for one timeout per ticker. A 401/404 only affects that ticker.
- **The API token stays on the server**, in a `.env` file that is never committed, and is sent in a header rather than in the URL (URLs end up in logs).
- **Income events come from B3's website, not from brapi.** brapi only offers them on a paid plan. B3 has no official API either: `b3.py` uses the JSON endpoints the website itself calls. They are undocumented and may change, so everything about them is isolated in that one module, and events already stored keep working if it breaks.
- **Events are matched by ISIN, not by name.** One issuer lists events for all its securities (common and preferred shares, subscription receipts). The ISIN encodes the kind (`BRBBASACNOR3` is BBAS3, a common share), and also tells funds apart from companies, so an FII amortization (capital returned) is never counted as income.
- **Positions depend on market data, but are still never stored.** Every calculation (validating a sale, deleting a trade, the portfolio, income) uses the same `calculate_position` with the stock events, so after a 1:2 split, selling the doubled amount is accepted everywhere. Other corporate actions (spin-offs, capital reductions) need more than a factor and are not handled.
- **Events are kept forever, synced once a day.** B3 shows only about 12 months of income history (stock events go back decades). Each sync replaces the window B3 returned (so corrections apply) and keeps everything older. Events are announced days ahead, so a daily sync loses nothing and makes one request per ticker per day.
- **Only market data is stored, never what you received.** Events (value per share) are stored like quotes; your income is computed from them and your trades.
- **Historical prices come from B3's official COTAHIST files, unadjusted.** brapi's history is limited to 3 months on the free plan. Adjusted prices (like "adjusted close" elsewhere) would also be wrong here: splits and income are already applied by this project, so they would count twice.
- **The first history download runs in the background.** A year of trades needs about 100 MB (one file per month), so `/performance` answers at once with what is stored, starts the download as a FastAPI background task and returns `syncing: true`; a lock keeps two downloads from running together. After that, each day adds one 550 KB file.
- **What to download is derived, not scheduled.** The periods needed (closed months as one file, the current month day by day, until yesterday) are compared with the ones recorded as loaded. Weekdays without a file are holidays and are recorded too. Every ticker of each day is stored (about 30,000 prices a month), so a ticker added later already has its history.
- **One injectable clock.** Market data uses the same clock for "today" and for load timestamps. Mixing a fake "today" with the real clock made tests pass only on the day they were written.
- **The CDI history must reach back to the oldest investment.** Being downloaded today is not enough: registering a CDB from last year makes the CDI be fetched again from that date.
- **New tables, no migration.** Income has no quantity or price, so it isn't stored as a kind of trade. Adding tables is the safest schema change: existing databases get them on startup and no existing column changes.
- **Passwords are hashed with Argon2id**, OWASP's first recommendation: a random salt per password and a deliberately slow, memory-hungry function, so a stolen database is expensive to brute force. Lengths follow NIST (at least 8, long passphrases allowed, with an upper bound because hashing has a cost). Hashes made with weaker parameters are upgraded at the next login, the only moment the password is available.
- **Sessions are opaque tokens, not JWTs.** The client gets 256 random bits; the database keeps only their SHA-256, so reading the database doesn't give anyone a session. Logging out deletes the row, which a JWT can't do without a list of revoked tokens.
- **Failed logins are limited**: 5 per email and IP, and 20 per IP, in a sliding 15-minute window (`429` with `Retry-After`). Counting by email and IP together, not by email alone, means nobody can lock a victim out by typing their email wrong on purpose. The counts are in memory, which is enough for a single server process.
- **Login errors don't reveal accounts.** A wrong email and a wrong password give the same message, and take the same time: an unknown email is still checked against a dummy hash.
- **Every row of user data has an owner, and every query filters by it.** Another user's row by id answers 404, exactly like a missing one, so ids reveal nothing. Market data (quotes, CDI, B3 events) is shared. A test walks through every route of the API and fails if one answers without a session, so a future endpoint can't forget it.
- **The first real migration.** Until v0.4, new tables were enough (`create_all`). Adding an owner to tables that already have data needs migrations, so v0.5 brings Alembic. The baseline migration only creates missing tables, so databases from before and new ones follow the same path; the first account created adopts the data from before accounts existed. `bonus_costs` changes its primary key, which Alembic can't detect, so it is rebuilt by hand.
- **The trade statement, not the movement one.** B3's movement statement ("Movimentação") is dated by settlement, two business days after the trade. A buy on a record date would show up after it, and its income and the order of the trades would be wrong.
- **Uploaded files are untrusted.** The file goes as the raw request body (no multipart parser needed), files over 5 MB are refused from the `Content-Length` header before being read, and openpyxl parses the XML through `defusedxml`. The login check runs before the upload is read: FastAPI resolves dependencies in parameter order.
- **B3's spreadsheets declare a wrong size** (`<dimension ref="A1"/>`), and openpyxl's fast mode trusts it and reads a single cell; the size is recomputed before reading. Numbers come as Excel floats and are turned into `Decimal` through `repr`, which gives back the decimal that was typed.
- **The frontend never imports the backend.** It only talks to the API over HTTP. That is what let the first UI (Streamlit, until v0.7) be replaced by React without touching the backend.
- **The frontend is typed from the API.** `investtrack/openapi.py` exports the OpenAPI schema to `web/openapi.json`, and `openapi-typescript` turns it into TypeScript types: a wrong path, a renamed field or a new enum value is a compile error. A Python test fails if the committed schema is stale, so the two sides can't drift apart silently. Enums (`OpType`, statuses, skip reasons) are typed as closed unions, and every label map is a `Record` over them, so a new value breaks the build until it has a Portuguese name.
- **The browser formats money without floats too.** The API sends decimals as strings; `format.ts` rounds them on their digits with `BigInt`, half to even like Python's `Decimal`, and sums and averages exactly. `Number` is used only to draw charts, where a pixel can't be off by a cent. Python writes some decimals with an exponent (a closed position is `"0E-8"`), so the parser reads that form as well.
- **The server owns the data, the browser caches it.** TanStack Query keeps one cache of what the API returned; screens read from it instead of copying it into component state. After any change everything is refetched: one trade moves positions, computed income, stock events and the TWR, and only the API knows how. Screens that wait for a background download (CDI, history) poll until it ends instead of asking the user to reload.
- **Same origin, no CORS.** The API lives under `/api` and the same server sends the web app for every other path (in development, Vite forwards `/api` to uvicorn). Reloading `/proventos` gets `index.html`, and the React router shows the page. Built files have a hash in their names, so they are cached forever; `index.html` is never cached, so a deploy shows at once. Logging out or an expired session (any `401`) empties the cache, so the next person on the same browser never sees cached data.
- **The session is an HttpOnly cookie, not a token in JavaScript.** Until v1.0 the token was kept in `localStorage`, where any script injected into the page could read it. Now the login sets a cookie that is `HttpOnly` (scripts can't read it, and the token is never in a response body), `SameSite=Strict` (the browser doesn't send it on requests started by another site, which is what a CSRF attack needs), `Secure` over HTTPS, and limited to `/api`. The app can't see the cookie, so on startup it asks `/api/auth/me` whether it is logged in.
- **An unknown total is shown as unknown.** While the CDI history is still downloading, an investment has no value yet. Summing only the valued ones would show a smaller net worth as if it were right, so `/portfolio` returns `fixed_income: null` and `syncing: true`, the Carteira shows "—" with a notice, and asks again until the value is known.
- **Quantities times prices are exact in the browser too.** `multiplyDecimals` multiplies the decimal strings with `BigInt` (an operation's total, quantity × price ± fees), so `0.1 × 0.2` is `0.02`, not `0.020000000000000004`.
- **Changing the password or deleting the account asks for the password**, so a session left open on someone else's computer is not enough. A wrong one answers `403`, not `401`: any `401` means "no session" and logs the app out. Changing the password ends every other session; deleting the account removes its rows one table at a time, since SQLite only cascades deletes with foreign keys switched on.
- **One container.** The [Dockerfile](Dockerfile) builds the React app with Node in a first stage and copies only the result into the Python image. The server runs as an unprivileged user, with a home of its own: with root's `HOME` left in place, PostgreSQL's client library looked for a certificate in `/root` on every SSL connection and failed with "permission denied". Behind the host's proxy, uvicorn trusts the forwarded headers, so the login limit sees each client's own IP and the cookie is marked `Secure`.
- **SQLite locally, PostgreSQL deployed.** SQLite needs no setup and is a single file, which suits development and a server with a disk. Free hosts have no persistent disk, so the deployed app uses PostgreSQL on Neon, through the same SQLAlchemy code. The whole test suite runs on both in CI, so a query that only works on one of them fails there. Connections are checked before use, since Neon closes them when it suspends an idle database.
- **Built for a small server.** The free plan has 512 MB of memory. A month of COTAHIST is about 10 MB zipped but ten times that unzipped, so it is read line by line straight out of the zip instead of decoded whole: the peak went from about 440 MB to under 70 MB.
- **The backend has layers, and a test keeps them.** `core` (pure calculations) imports nothing else from the project, `sources` turn outside data into `core`'s types, `storage` uses both, and `api` uses everything. [`tests/test_architecture.py`](tests/test_architecture.py) reads every import and fails on one in the wrong direction.

## Testing

```bash
pytest --cov
```

445 tests, 98% coverage. Tests never touch the internet: the HTTP session, the quote source and even the clock are replaced by fakes, so they are fast, deterministic and don't spend the API quota. They run on an in-memory SQLite database, and on PostgreSQL when `TEST_DATABASE_URL` is set.

```bash
cd web && npm test
```

108 frontend tests ([Vitest](https://vitest.dev) and Testing Library) drive the screens like a user (typing, clicking, uploading a statement) against a fake API, and check what is shown and what is sent.

Every push runs, with [GitHub Actions](.github/workflows/ci.yml), the linter, the formatter check and the tests on Python 3.12 and 3.14, the tests again on PostgreSQL, the frontend's linter, type check, tests and build, and builds the Docker image.

The calculation tests include the worked example used to design the rules:

| Trade | Quantity | Average cost | Realized profit |
|---|---|---|---|
| Buy 100 PETR4 at R$ 30 | 100 | R$ 30.00 | R$ 0 |
| Buy 100 PETR4 at R$ 40 | 200 | R$ 35.00 | R$ 0 |
| Sell 50 PETR4 at R$ 50 | 150 | R$ 35.00 (unchanged) | R$ 750 |
| Quote at R$ 38 | 150 | R$ 35.00 | Unrealized: R$ 450 (+8.57%) |

## Getting started

Requires Python 3.12+ and Node.js 20.19+ or 22.12+ (what Vite 8 needs).

```bash
git clone https://github.com/samuel-mendes-monteiro/InvestTrack.git
cd InvestTrack
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cd web && npm ci && cd ..
```

Tests use an in-memory SQLite database. To run them on PostgreSQL too, as CI does, point `TEST_DATABASE_URL` at an empty database (every table in it is dropped):

```bash
TEST_DATABASE_URL=postgresql://user:pass@localhost/investtrack_test pytest
```

Quotes come from brapi.dev. Copy the example settings and add your free brapi token (without a token, only PETR4, VALE3, MGLU3 and ITUB4 work):

```bash
cp .env.example .env
```

Optionally, create a database with a demo account, sample trades, income and fixed income (it prints the email and password to log in with):

```bash
python -m investtrack.demo
```

Or create your own account on the login screen. Migrations run when the API starts; to create a new one after changing the models, use `alembic revision --autogenerate -m "..."`.

Start the API (interactive docs at http://localhost:8000/api/docs):

```bash
uvicorn investtrack.api:app --reload
```

In another terminal, start the web interface (http://localhost:5173):

```bash
cd web
npm run dev
```

After changing the API's routes or schemas, regenerate the frontend's types (and fix whatever no longer type-checks):

```bash
cd web
npm run gen:api
```

### Running it like production

The image serves the API and the web app together on port 8000:

```bash
docker build -t investtrack .
docker run -p 8000:8000 -v investtrack-data:/data --env-file .env investtrack
```

### Deploying for free: Render + Neon

This is how [investtrack.online](https://investtrack.online) runs. [Render](https://render.com)'s free plan runs the Docker image but has no disk, so the database is PostgreSQL on [Neon](https://neon.tech)'s free plan. [`render.yaml`](render.yaml) has the settings.

1. On Neon, create a project in **AWS US East 1 (N. Virginia)** and copy its connection string.
2. On Render, **New → Blueprint**, pick this repository, and fill in `DATABASE_URL` (the Neon string) and `BRAPI_TOKEN`.
3. Every push to `main` deploys again. Migrations run when the app starts.
4. For your own domain: on Render, **Settings → Custom Domains**, then at the domain's DNS an `A` record for `@` pointing to `216.24.57.1` and a `CNAME` for `www` pointing to the service's `onrender.com` address. Render issues the HTTPS certificate and redirects `www` to the bare domain.

The service's `onrender.com` address gets a random suffix and keeps it: renaming the service doesn't change it. The free service sleeps after 15 minutes without visits, and the next visit takes about a minute to wake it. A year of B3 history takes about 35 MB of the database.

### API

Every route is under `/api`. All except `/api/health`, `/api/auth/register` and `/api/auth/login` need the session cookie that `/api/auth/login` sets (with curl: `-c cookies.txt` on the login, `-b cookies.txt` afterwards).

| Method | Route | Description |
|---|---|---|
| `POST` | `/auth/register` | Create an account (409 if the email is taken) |
| `POST` | `/auth/login` | Start a session, valid for 30 days, in an HttpOnly cookie (429 after too many failures) |
| `POST` | `/auth/logout` | End the session |
| `GET` | `/auth/me` | The logged-in user, and since when the account exists |
| `POST` | `/auth/password` | Change the password (403 if the current one is wrong); ends every other session |
| `POST` | `/auth/delete-account` | Delete the account and all of its data, after the password |
| `POST` | `/operations` | Record a buy or sell (422 if selling more than owned) |
| `GET` | `/operations` | List operations, optionally filtered by `?ticker=` |
| `PUT` | `/operations/{id}` | Edit an operation, e.g. to add the fees of an imported trade (409 if a sale or an income would be left without shares) |
| `DELETE` | `/operations/{id}` | Delete an operation (409 if a later sale or an income depends on it) |
| `GET` | `/income` | Computed and manual income, including pending; filter by `?ticker=` and `?year=` |
| `GET` | `/income/monthly` | Net income received per month and type, optionally for one `?year=` |
| `POST` | `/income` | Record income manually (422 if the ticker wasn't bought by then) |
| `DELETE` | `/income/{id}` | Delete a manual income |
| `GET` | `/stock-events` | Splits, reverse splits and bonus shares that changed one of your positions |
| `PUT` | `/stock-events/{ticker}/{date}/unit-cost` | Attributed cost of a bonus event (404 if there is no bonus on that date) |
| `DELETE` | `/stock-events/{ticker}/{date}/unit-cost` | Back to zero cost |
| `GET` | `/portfolio` | Positions, live prices, income received and portfolio totals (`syncing` while fixed income is being valued) |
| `GET` | `/prices/{ticker}` | Price for a new trade: the current quote, or B3's close for an earlier `?date=` (404 if unknown) |
| `POST` | `/fixed-income` | Register a CDB, LCI or LCA: % of CDI, pre-fixed or IPCA+ |
| `GET` | `/fixed-income` | Each investment with gross value, IOF, income tax and net value |
| `PUT` | `/fixed-income/{id}` | Edit an investment (422 if a withdrawal no longer fits) |
| `PUT` | `/fixed-income/{id}/redemption` | Early redemption on a date (`null` undoes it) |
| `POST` | `/fixed-income/{id}/partial-redemptions` | Withdraw part of an investment (422 if not less than its value that day) |
| `DELETE` | `/fixed-income/{id}/partial-redemptions/{rid}` | Undo a partial redemption |
| `DELETE` | `/fixed-income/{id}` | Delete an investment |
| `POST` | `/imports/b3/preview` | What importing a B3 trade statement (raw `.xlsx` body) would add; saves nothing |
| `POST` | `/imports/b3` | Import the statement's new trades in one transaction |
| `GET` | `/performance` | Daily TWR (with and without income), CDI, Ibovespa, net worth and money put in, for `?period=7D`, `1M`, `6M`, `1Y` or `ALL` (downloads missing history in the background) |
| `GET` | `/health` | Health check |

### Configuration

| Variable | Default | Description |
|---|---|---|
| `BRAPI_TOKEN` | *(empty)* | brapi.dev token |
| `PRICE_CACHE_MINUTES` | `15` | How long a quote is reused |
| `DATABASE_URL` | `sqlite:///investtrack.db` | SQLite or PostgreSQL (`postgres://` and `postgresql://` URLs use psycopg 3) |
| `PORT` | `8000` | Port the Docker image listens on (Render sets it) |
| `API_URL` | `http://localhost:8000` | Where the frontend's dev server forwards `/api` (read by `npm run dev`) |
| `WEB_DIST` | *(empty)* | The built web app (`web/dist`) for the API to serve; set in the Docker image |

## Roadmap

- [x] Calculation core with tests
- [x] Database (SQLAlchemy)
- [x] REST API (FastAPI)
- [x] Live quotes (brapi) with caching
- [x] Streamlit UI (replaced by React in v1.0)
- [x] CI with GitHub Actions
- [x] **v0.2:** dividends, JCP and REIT (FII) income
- [x] Stock splits, reverse splits and bonus shares
- [x] Attributed cost of bonus shares (*custo atribuído*)
- [x] **v0.3:** historical performance with time-weighted return (TWR), compared with CDI and Ibovespa
- [x] **v0.4:** fixed income (CDB, LCI, LCA)
- [x] **v0.5:** login and multiple users
- [x] **v0.6:** import B3 trade statements
- [x] **v0.7:** partial redemptions and IPCA+ fixed income, editing operations, login rate limiting
- [x] **v1.0:** React + TypeScript frontend, typed from the API's OpenAPI schema
- [x] **v1.0:** one Docker image with the API and the web app, session in an HttpOnly cookie
- [x] **v1.1:** live at [investtrack.online](https://investtrack.online), free on Render with PostgreSQL on Neon; backend split into layers
- [x] **v1.1:** redesigned screens, Patrimônio page with the gain net of deposits, return split into prices and income, product page, onboarding and import guide, price suggestions, profile with password change and account deletion, editable fixed income

## License

[MIT](LICENSE)

# InvestTrack

> A personal investment portfolio tracker for the Brazilian stock market (B3).

🚧 **Status:** early development. See the [roadmap](#roadmap) below.

## The problem

People who invest through more than one broker don't get a single view of their portfolio. Each broker's app shows its own account only. Spreadsheets take effort, break easily and rarely calculate the **average cost** and **returns** correctly.

## The solution

InvestTrack is a web app where you record your buy and sell trades and get back:

- your current position in each asset
- the average cost (*preço médio*)
- realized and unrealized profit/loss, in R$ and in %
- how your portfolio is split across assets

Quotes from B3 are updated automatically.

## Core design principle

**The trade history is the single source of truth.**

Positions (quantity, average cost) are **never stored** in the database. They are always **recalculated** from the list of trades. Editing or deleting an old trade therefore updates everything automatically, and the data can never become inconsistent.

## MVP scope

| In the MVP | Later (roadmap) |
|---|---|
| Record buy/sell trades (ticker, date, quantity, price, fees) | Dividends, JCP and REIT (FII) income |
| List and delete trades | Historical performance chart |
| Position, average cost and realized profit | Benchmark against CDI and Ibovespa |
| Live quotes, with results in R$ and % | Fixed income (CDB, LCI, LCA) |
| Portfolio allocation chart | Login and multiple users |
| Stocks, FIIs, ETFs and BDRs | B3 statement import and tax (IR) calculation |

## Tech stack

| Layer | Technology |
|---|---|
| Language | Python 3.12+ |
| API | FastAPI + Pydantic |
| Database | SQLite (dev), PostgreSQL (prod) via SQLAlchemy 2.0 |
| Market data | [brapi.dev](https://brapi.dev) |
| UI (MVP) | Streamlit + Plotly |
| UI (v1.0) | React |
| Tests | pytest |

## Calculation rules

**Buy:** the average cost is recalculated, and fees are added to the cost.

```
new_avg = (current_qty × current_avg + bought_qty × price + fees) / (current_qty + bought_qty)
```

**Sell:** the average cost **does not change**. The difference becomes realized profit (or loss).

```
realized_profit += sold_qty × (sell_price − avg) − fees
```

Trades are processed **in date order** (not in the order they were entered), and a sale can never leave a negative quantity.

## Technical decisions

- **No `float` for money.** `Decimal` in Python and `Numeric` in the database, because `0.1 + 0.2 != 0.3` in floating point.
- **Calculations are isolated** in a pure module with no database or HTTP access. It takes a list of trades and returns positions, which makes it easy to test.
- **The API token stays on the server.** The frontend never calls brapi directly.
- **Quotes are cached** for about 15 minutes per ticker. If the API is down, the last known price is used.

## Roadmap

- [ ] **Stage 0:** project setup
- [ ] **Stage 1:** pure calculation logic + tests
- [ ] **Stage 2:** database (SQLAlchemy)
- [ ] **Stage 3:** REST API (FastAPI)
- [ ] **Stage 4:** live quotes (brapi) with caching
- [ ] **Stage 5:** Streamlit UI
- [ ] **Stage 6:** CI with GitHub Actions + polish

After the MVP: dividends (v0.2), time-weighted return (v0.3), fixed income (v0.4), authentication (v0.5), B3 import (v0.6), React frontend + deployment (v1.0).

## Getting started

```bash
git clone https://github.com/samuel-mendes-monteiro/InvestTrack.git
cd InvestTrack
python3 -m venv .venv
source .venv/bin/activate
```

More instructions will be added as the project grows.

## License

[MIT](LICENSE)

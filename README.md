# Weekly stock scanner

Scans about 220 liquid US stocks with free end of day data from Yahoo Finance. It writes one report with four sections:

1. **Swing breakouts.** Price is above a rising 50 and 200 day average, sitting in a tight base within 5% of the 50 day high, on drying volume, and beating SPY over 3 months. Earnings must be at least 14 days out. Each name gets an entry, stop, 2R and 3R targets, and a share count.
2. **Cash secured puts.** The stock is above its 200 day, priced $20 to $150, liquid, and worth over $10B. The put has 25 to 50 days to expiration, with no earnings before expiration. The strike sits at real support, and the report shows premium, annualized return, breakeven, and cushion.
3. **Covered calls** on the stocks you list in `settings.json`. The strike is at or above the 50 day high and never below your cost basis.
4. **Long term themes.** Fundamentals for the tickers in `themes.json`: growth, margins, free cash flow, debt, forward P/E, and PEG.

## Run it

```
pip install -r requirements.txt
python scan.py            # all four sections
python scan.py swing csp  # only some sections: swing, csp, cc, long
```

The report goes to `output/YYYY-MM-DD-watchlist.md`, with a CSV for each section. A full run takes a few minutes because each put candidate needs its own option chain request.

## Set it up for you

Edit `settings.json`:

- `account.size`: your account value.
- `account.risk_per_trade_pct`: 0.01 means a swing trade stop out loses 1% of the account.
- `account.max_position_pct`: the biggest single position as a share of the account.
- `holdings`: your stocks for covered calls, for example `{"ticker": "AAPL", "shares": 200, "cost_basis": 185}`.

Edit `universe.txt` to add or remove stocks, and `themes.json` to change the long term themes.

## Limits

- Yahoo data is free and unofficial. It can be late or have gaps, and the earnings date is sometimes missing. A missing date shows as `CHECK`: look it up before you trade.
- True IV rank needs a year of implied volatility history, which isn't free. The put scan uses `iv_to_hv` instead, which is implied vol divided by 20 day realized vol. Above 1 means option premium is rich compared with how much the stock actually moves.
- Option prices are taken at the mid. Fills on wider markets will be worse.
- This is a screen, not a signal. Check every chart on TrendSpider before you place an order.

## Tests

```
python -m pytest tests
```

The tests use synthetic prices and a fake data source, so they run without network access.

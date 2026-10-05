# Money Trail

A research dashboard that follows the money. Every day it answers four questions:

1. **What changed?** A daily brief at 6am Pacific with second order thinking: who pays, who gets paid, what becomes scarce.
2. **Where is the money flowing?** Supply chain maps for each theme, from raw materials to end customers, with chokepoint suppliers flagged.
3. **Who is putting their own money in?** Insider open market buys (strongest evidence) and Congress trades (leaders weighted up, everyone else is a clue).
4. **Is the chart ready?** Swing breakout and cash secured put setups, tagged with their themes.

The **Lineup** tab combines all four: chokepoint or pure play, insider buying, Congress leader buying, trend and setup.

## How it runs

- **GitHub Actions** (`.github/workflows/refresh.yml`) pulls prices from Yahoo Finance, insider buys from OpenInsider, and Congress trades from Quiver Quantitative or the House Clerk every weekday after the close. Then it rebuilds and deploys the site to GitHub Pages.
- **A daily Claude research run** reads the news and the data, writes `research/briefs/<date>.json`, updates the theme maps, and adds new themes when new money starts moving. Instructions are in `research/ROUTINE.md`.

## Run it yourself

```
pip install -r requirements.txt
python update.py            # pull data and rebuild site/data
python update.py --offline  # rebuild from saved data only
cd site && python -m http.server 8000   # open http://localhost:8000
python scan.py              # the original weekly report, including covered calls on your holdings
```

## Privacy

The repo is public. Account size and holdings never go in it.

- On the site, type your account size into the Setups tab. It stays in your browser.
- For `scan.py` covered calls, copy `private.example.json` to `private.json` (gitignored) and fill it in.

## Limits

Free data can be late, missing or wrong. Congress filings can be 45 days old. True IV rank needs paid data, so put ideas use implied vol divided by realized vol. This is research, not advice. Check every chart before you trade.

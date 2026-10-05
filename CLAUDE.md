# Money Trail

Market research dashboard for one investor (swing trades, cash secured puts, covered calls, long term).
Method: follow the money, find chokepoints, confirm with insider and Congress buying and the chart.

- `research/themes/*.json`: supply chain maps per theme. `research/briefs/*.json`: daily briefs.
- `research/ROUTINE.md`: what the daily 6am Pacific research run does. Follow it when asked for a brief.
- `stockscan/`: Python. `update.py` builds `site/data/` (`--offline` skips the network).
- `site/`: static dashboard (plain HTML/CSS/JS), deployed to GitHub Pages by `.github/workflows/refresh.yml`.
- The repo is public. Never commit account size, holdings or anything personal. `private.json` is gitignored.
- Tests: `python -m pytest tests` (offline, synthetic data).
- Writing style for anything she reads: plain language, short sentences, no em dashes, no hype.

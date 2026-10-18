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
- Never write the private owner link, or any URL containing `owner=`, into the repo, a brief, the Drive copy or
  anything public. Never send her personal email to outside services; the SEC User-Agent uses her GitHub noreply
  address. (2026-10)
- Keep other parts of her life out of this repo: work lists, names of colleagues or clients, family business data.
  If something from another lane shows up, do not save it here. (2026-10-14)
- Push back before building. When she asks for a feature, give a verdict first (good idea, weak idea, or a better
  idea) and say why, then build what she picks. Don't just build it. (2026-10-12)
- Tell her about data problems you find (stale prices, a check that passes when it should fail) and fix the code
  with a test when you can.
- No model names in commits, briefs or code comments.
- `site/app.js` has `YOUTUBE_URL = ""`. The explainer video slot stays hidden until she gives a link.
- When reporting to her about this project, always end with the links:
  dashboard https://sandiejotrina.github.io/stock-scanner/ and repo https://github.com/sandiejotrina/stock-scanner

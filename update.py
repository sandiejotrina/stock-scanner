"""Refresh the dashboard data.

    python update.py            pull prices, insider buys and Congress trades, then rebuild
    python update.py --offline  rebuild from research files and the last saved data (no network)
"""

import sys

from stockscan.site_data import build

if __name__ == "__main__":
    meta = build(offline="--offline" in sys.argv)
    print(f"Built site data at {meta['generated']}")
    for e in meta["errors"]:
        print(f"  problem: {e}")

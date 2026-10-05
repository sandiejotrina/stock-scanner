"""Weekly stock scanner.

    python scan.py              run all four sections
    python scan.py swing csp    run only the sections named (swing, csp, cc, long)
"""

import sys

from stockscan.runner import run

if __name__ == "__main__":
    buckets = tuple(sys.argv[1:]) or ("swing", "csp", "cc", "long")
    path = run(buckets=buckets)
    print(f"Report written to {path}")

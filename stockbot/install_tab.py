#!/usr/bin/env python3
"""Adds the Stocks tab to the memebot dashboard. Safe to run twice.

    python3 install_tab.py                       # patches ~/memebot/dashboard.py
    python3 install_tab.py /path/to/dashboard.py

It makes a backup next to the file (dashboard.py.bak-stocks), changes three
spots, and stops without touching anything if the file does not look the way
it expects. Restart the dashboard afterwards.
"""

import os
import shutil
import sys

STOCKBOT_DIR = os.path.dirname(os.path.abspath(__file__))
target = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else "~/memebot/dashboard.py")

src = open(target).read()
OLD_ROUTE = '            if u.path in ("/stocks", "/s", "/approve") and stocks_page:\n'
NEW_ROUTE = '            if stocks_page and stocks_page.handles(u.path):\n'
GUARD = ('            if stocks_page and hasattr(stocks_page, "guard"):\n'
         '                u = u._replace(path=stocks_page.guard(u.path, self.headers))\n')


def upgrade(src):
    """Bring an already-patched dashboard.py up to date. Returns the new text."""
    if OLD_ROUTE in src:                       # Filings tab route
        src = src.replace(OLD_ROUTE, NEW_ROUTE)
        print("upgraded the route for the Filings tab")
    if "stocks_page.guard" not in src and NEW_ROUTE in src:   # share-link guard
        src = src.replace(NEW_ROUTE, GUARD + NEW_ROUTE, 1)
        print("added the share-link guard (friends only see Stocks + Filings)")
    return src


if "stocks_page" in src:
    new = upgrade(src)
    if new != src:
        shutil.copy(target, target + ".bak-stocks2")
        open(target, "w").write(new)
        print("Restart the dashboard.")
    else:
        print("already patched: nothing to do")
    sys.exit(0)

IMPORT_ANCHOR = 'CHAINS = {"solana", "base", "robinhood"}\n'
NAV_ANCHOR = '    out.append("<h1>memebot</h1>")\n'
ROUTE_ANCHOR = '            if u.path == "/c":\n'

for a in (IMPORT_ANCHOR, NAV_ANCHOR, ROUTE_ANCHOR):
    if src.count(a) != 1:
        sys.exit("dashboard.py doesn't match what I expect (could not find: %r). Nothing changed." % a.strip())

import_block = IMPORT_ANCHOR + (
    "\n# --- stocks tab ---\n"
    "import sys as _sys\n"
    "_sys.path.insert(0, %r)\n"
    "try:\n"
    "    import stocks_page\n"
    "except Exception:\n"
    "    stocks_page = None\n"
    "# --- end stocks tab ---\n" % STOCKBOT_DIR)
nav_block = NAV_ANCHOR.replace(
    '    out.append("<h1>memebot</h1>")\n',
    '    if stocks_page:\n        out.append(stocks_page.tabs("memebot"))\n    out.append("<h1>memebot</h1>")\n')
route_block = (
    '            if stocks_page and stocks_page.handles(u.path):\n'
    '                body = stocks_page.render(u.path, parse_qs(u.query), CSS).encode()\n'
    '            elif u.path == "/c":\n')

new = upgrade(src.replace(IMPORT_ANCHOR, import_block).replace(NAV_ANCHOR, nav_block).replace(ROUTE_ANCHOR, route_block))
shutil.copy(target, target + ".bak-stocks")
with open(target, "w") as f:
    f.write(new)
print("patched %s (backup: %s.bak-stocks). Restart the dashboard." % (target, target))

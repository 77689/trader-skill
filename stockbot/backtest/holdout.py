"""Holdout rule: new ideas are designed and tuned only on data BEFORE HOLDOUT_START.
The holdout (that date onward) is looked at ONCE per idea, as a final exam. Every look is
logged in the vault's bots/tries.md. Peeking again and tweaking means it is no longer a test."""
HOLDOUT_START = "2024-01-01"

def is_holdout(date):
    """date as 'YYYY-MM-DD' string (or anything that sorts like one)."""
    return str(date)[:10] >= HOLDOUT_START

def split(dates, *series):
    """Cut dates (and any same-length series) at the holdout start.
    Returns (before, after); each is a list [dates, *series]."""
    i = sum(1 for d in dates if not is_holdout(d))  # dates are in order, so count = cut point
    cols = (dates,) + series
    return [c[:i] for c in cols], [c[i:] for c in cols]

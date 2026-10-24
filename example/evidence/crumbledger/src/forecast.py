"""Demand forecast: last four same-weekdays, averaged; a holiday multiplier on the days the owner marks."""
HOLIDAY_MULTIPLIER = 1.6


def demand(item, history, holiday=False):
    base = sum(history[-4:]) / max(1, len(history[-4:]))
    return base * (HOLIDAY_MULTIPLIER if holiday else 1.0)

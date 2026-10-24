"""Reorder points: seven days of usage, the supplier's lead time, a 20% cushion. Thresholds come from configs/thresholds.yml."""
import yaml

CUSHION = 1.2


def point_for(item, usage_7d_g, lead_days):
    """Grams to hold before reordering `item`: average daily use over the lead time, plus the cushion."""
    return usage_7d_g / 7 * lead_days * CUSHION


def thresholds(path="configs/thresholds.yml"):
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}

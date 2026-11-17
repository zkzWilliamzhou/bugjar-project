"""Delta debugging over World units. Deep interface: units + oracle -> subset."""
from __future__ import annotations

from typing import List


class BudgetExhausted(Exception):
    pass


def ddmin(units: List[str], oracle) -> List[str]:
    """Complement testing at increasing granularity, then a 1-minimal pass."""
    current = list(units)
    granularity = 2
    while len(current) >= 2:
        chunks = [current[i::granularity] for i in range(granularity)]
        chunks = [c for c in chunks if c]
        reduced = False
        for chunk in chunks:
            drop = set(chunk)
            complement = [u for u in current if u not in drop]
            if complement and oracle(complement):
                current = complement
                granularity = max(2, granularity - 1)
                reduced = True
                break
        if not reduced:
            if granularity >= len(current):
                break
            granularity = min(len(current), granularity * 2)
    changed = True
    while changed:
        changed = False
        for unit in list(current):
            complement = [u for u in current if u != unit]
            if oracle(complement):
                current = complement
                changed = True
    return current

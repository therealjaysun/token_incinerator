from __future__ import annotations

import math
from typing import Callable

_STATISTICAL_RATE_PER_HOUR = 120

_WORK_THRESHOLD = 0.05


def sample_statistical_delay_ms(random_fn: Callable[[], float]) -> float:
    """Sample a Poisson-distributed delay to mimic natural developer pacing.

    Mean delay is based on ~120 requests/hour (~30s between requests on average).
    """
    rate_per_ms = _STATISTICAL_RATE_PER_HOUR / 3_600_000
    u = max(random_fn(), 1e-10)
    return -math.log(u) / rate_per_ms


def is_within_work_window(hour: int) -> bool:
    """True when the given local hour falls inside the simulated workday."""
    return workday_weight(hour) >= _WORK_THRESHOLD


def seconds_until_work_window(hour: int) -> float:
    """Return seconds until the next hour where workday_weight >= threshold.

    Called when current hour is outside the work window. Returns how long
    to sleep before rechecking. Always returns a positive value.
    """
    for hours_ahead in range(1, 25):
        candidate = (hour + hours_ahead) % 24
        if workday_weight(candidate) >= _WORK_THRESHOLD:
            return hours_ahead * 3600.0
    return 3600.0  # fallback: try again in an hour


def workday_weight(hour: int) -> float:
    """Return a 0.0–1.0 activity weight for the given hour of day (0–23).

    Peaks around 10am and 2pm, low at night.
    """
    # Two Gaussian peaks: 10am and 14pm, sigma ~2 hours each
    def gaussian(x: float, mu: float, sigma: float) -> float:
        return math.exp(-0.5 * ((x - mu) / sigma) ** 2)

    peak1 = gaussian(hour, 10, 2.0)
    peak2 = gaussian(hour, 14, 2.0)
    return min(1.0, max(0.0, max(peak1, peak2)))

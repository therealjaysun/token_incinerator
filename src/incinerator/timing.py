from __future__ import annotations

import math
from typing import Callable


def sample_exponential_ms(rate_per_hour: int, random_fn: Callable[[], float]) -> float:
    """Sample inter-arrival delay in milliseconds from an exponential distribution.

    Models requests arriving as a Poisson process at the given rate.
    Mean delay = 3_600_000ms / rate_per_hour.
    """
    rate_per_ms = rate_per_hour / 3_600_000
    u = random_fn()
    # Clamp to avoid log(0)
    u = max(u, 1e-10)
    return -math.log(u) / rate_per_ms


def sample_session_duration_ms(random_fn: Callable[[], float]) -> float:
    """Sample a work session duration in milliseconds from a log-normal distribution.

    Centered around 2.5 hours, clamped to [30 min, 6 hours].
    """
    import math

    # log-normal with mean ~2.5 hours: mu and sigma in log space
    # E[X] = exp(mu + sigma^2/2), target E[X] = 2.5h
    mu = math.log(2.5 * 3600 * 1000) - 0.5 * 0.4 ** 2
    sigma = 0.4
    u1 = max(random_fn(), 1e-10)
    u2 = random_fn()
    # Box-Muller transform for standard normal
    z = math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2)
    raw = math.exp(mu + sigma * z)
    min_ms = 30 * 60 * 1000
    max_ms = 6 * 60 * 60 * 1000
    return max(min_ms, min(max_ms, raw))


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

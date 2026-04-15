import math
import random

import pytest

from incinerator.timing import (
    sample_exponential_ms,
    sample_session_duration_ms,
    workday_weight,
)


def seeded(seed: int = 42):
    rng = random.Random(seed)
    return rng.random


class TestSampleExponentialMs:
    def test_returns_positive_value(self):
        delay = sample_exponential_ms(rate_per_hour=3600, random_fn=seeded())
        assert delay > 0

    def test_mean_approximates_expected_value(self):
        # At rate 3600 tokens/hour, mean inter-arrival for a Poisson process is ~1 second
        # But here rate_per_hour means "requests/hour", so mean = 3600000ms / rate = 1000ms
        samples = [
            sample_exponential_ms(rate_per_hour=3600, random_fn=seeded(i))
            for i in range(1000)
        ]
        mean = sum(samples) / len(samples)
        assert abs(mean - 1000) < 150  # within 15% of 1000ms

    def test_higher_rate_gives_shorter_delays(self):
        low_rate_delay = sample_exponential_ms(rate_per_hour=100, random_fn=seeded())
        high_rate_delay = sample_exponential_ms(rate_per_hour=10000, random_fn=seeded())
        # Statistical expectation: lower rate → longer mean delay
        # With same seed the ratio should hold directionally across samples
        low_rate_samples = [
            sample_exponential_ms(rate_per_hour=100, random_fn=seeded(i))
            for i in range(500)
        ]
        high_rate_samples = [
            sample_exponential_ms(rate_per_hour=10000, random_fn=seeded(i))
            for i in range(500)
        ]
        assert sum(low_rate_samples) > sum(high_rate_samples)

    def test_all_values_are_positive(self):
        samples = [
            sample_exponential_ms(rate_per_hour=5000, random_fn=seeded(i))
            for i in range(200)
        ]
        assert all(s > 0 for s in samples)


class TestSampleSessionDurationMs:
    def test_returns_positive_value(self):
        duration = sample_session_duration_ms(random_fn=seeded())
        assert duration > 0

    def test_duration_in_reasonable_range(self):
        # Sessions should be between 30 minutes and 6 hours
        samples = [
            sample_session_duration_ms(random_fn=seeded(i))
            for i in range(200)
        ]
        min_ms = 30 * 60 * 1000    # 30 minutes
        max_ms = 6 * 60 * 60 * 1000  # 6 hours
        assert all(min_ms <= s <= max_ms for s in samples)

    def test_mean_near_two_and_half_hours(self):
        samples = [
            sample_session_duration_ms(random_fn=seeded(i))
            for i in range(500)
        ]
        mean_hours = (sum(samples) / len(samples)) / (3600 * 1000)
        assert 1.5 <= mean_hours <= 4.0


class TestWorkdayWeight:
    def test_noon_has_higher_weight_than_midnight(self):
        assert workday_weight(12) > workday_weight(0)

    def test_noon_has_higher_weight_than_late_evening(self):
        assert workday_weight(12) > workday_weight(22)

    def test_weight_between_zero_and_one(self):
        for hour in range(24):
            w = workday_weight(hour)
            assert 0.0 <= w <= 1.0, f"hour {hour} gave weight {w}"

    def test_peak_hours_have_high_weight(self):
        # 9am-5pm should have weight above 0.5
        for hour in range(9, 17):
            assert workday_weight(hour) > 0.5, f"hour {hour} should be high activity"

    def test_night_hours_have_low_weight(self):
        for hour in [0, 1, 2, 3, 4, 5]:
            assert workday_weight(hour) < 0.3, f"hour {hour} should be low activity"

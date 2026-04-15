import math
import random

import pytest

from incinerator.timing import (
    is_within_work_window,
    sample_exponential_ms,
    seconds_until_work_window,
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


class TestIsWithinWorkWindow:
    def test_midday_is_within_window(self):
        assert is_within_work_window(10) is True
        assert is_within_work_window(14) is True

    def test_middle_of_night_is_outside_window(self):
        assert is_within_work_window(3) is False
        assert is_within_work_window(0) is False

    def test_consistent_with_workday_weight(self):
        for hour in range(24):
            assert is_within_work_window(hour) == (workday_weight(hour) >= 0.05)


class TestSecondsUntilWorkWindow:
    def test_returns_positive_value_for_night_hours(self):
        for hour in [0, 1, 2, 3, 4, 5]:
            assert seconds_until_work_window(hour) > 0

    def test_night_hour_waits_until_morning(self):
        # Hour 3am: next work window starts at ~6am → ~3 hours wait
        wait = seconds_until_work_window(3)
        assert 2 * 3600 <= wait <= 6 * 3600

    def test_midnight_waits_several_hours(self):
        # Hour 0: next work starts at ~6am → ~6 hours
        wait = seconds_until_work_window(0)
        assert wait >= 5 * 3600

    def test_late_night_wraps_to_next_day(self):
        # Hour 22 (10pm): next work starts ~6am next day → ~8 hours
        wait = seconds_until_work_window(22)
        assert wait >= 6 * 3600

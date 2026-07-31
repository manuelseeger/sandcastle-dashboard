"""Unit tests for CPU-percentage derivation from consecutive samples."""

from __future__ import annotations

from sandcastle_dashboard.resource_usage import ResourceUsageSampler


def test_sample_returns_none_on_the_first_observation_of_a_host_run():
    sampler = ResourceUsageSampler()

    cpu_percent = sampler.sample("run-1", cpu_seconds=1.0, sampled_at=100.0)

    assert cpu_percent is None


def test_sample_computes_percent_from_the_delta_since_the_previous_sample():
    sampler = ResourceUsageSampler()
    sampler.sample("run-1", cpu_seconds=1.0, sampled_at=100.0)

    cpu_percent = sampler.sample("run-1", cpu_seconds=2.0, sampled_at=102.0)

    # 1 cpu-second consumed over 2 wall-clock seconds = 50%
    assert cpu_percent == 50.0


def test_sample_tracks_each_host_run_id_independently():
    sampler = ResourceUsageSampler()
    sampler.sample("run-1", cpu_seconds=1.0, sampled_at=100.0)

    cpu_percent = sampler.sample("run-2", cpu_seconds=5.0, sampled_at=100.0)

    assert cpu_percent is None


def test_sample_returns_none_when_elapsed_time_is_zero_or_negative():
    sampler = ResourceUsageSampler()
    sampler.sample("run-1", cpu_seconds=1.0, sampled_at=100.0)

    cpu_percent = sampler.sample("run-1", cpu_seconds=2.0, sampled_at=100.0)

    assert cpu_percent is None


def test_sample_returns_none_when_cumulative_cpu_seconds_decreases():
    """A busy process can disappear between samples, making the tree's
    cumulative CPU seconds appear to drop. This must degrade to an unknown
    reading rather than a negative or misleading percentage."""
    sampler = ResourceUsageSampler()
    sampler.sample("run-1", cpu_seconds=5.0, sampled_at=100.0)

    cpu_percent = sampler.sample("run-1", cpu_seconds=3.0, sampled_at=101.0)

    assert cpu_percent is None


def test_sample_recovers_after_a_churn_sample_once_deltas_are_positive_again():
    sampler = ResourceUsageSampler()
    sampler.sample("run-1", cpu_seconds=5.0, sampled_at=100.0)
    sampler.sample("run-1", cpu_seconds=3.0, sampled_at=101.0)

    cpu_percent = sampler.sample("run-1", cpu_seconds=4.0, sampled_at=102.0)

    assert cpu_percent == 100.0

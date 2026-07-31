"""Derives Host Run CPU percentage from consecutive process-tree samples.

A single ``/proc`` scan only yields the tree's cumulative CPU-seconds.
Turning that into a percentage requires comparing two samples over time, so
this sampler retains the previous sample per Host Run id and derives the
rate between polls.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class _Sample:
    cpu_seconds: float
    sampled_at: float


class ResourceUsageSampler:
    """Tracks the previous CPU sample for each known Host Run id."""

    def __init__(self) -> None:
        self._previous: dict[str, _Sample] = {}

    def sample(
        self, host_run_id: str, cpu_seconds: float, sampled_at: float
    ) -> float | None:
        """Return the CPU percentage since the last sample for ``host_run_id``.

        Returns ``None`` on the first observation, when no wall-clock time
        has elapsed, or when cumulative CPU seconds decreased. The latter
        happens when a busy tree member disappears between samples: process
        churn must degrade to an unknown reading rather than a negative or
        misleading percentage.
        """
        previous = self._previous.get(host_run_id)
        self._previous[host_run_id] = _Sample(
            cpu_seconds=cpu_seconds, sampled_at=sampled_at
        )
        if previous is None:
            return None
        elapsed = sampled_at - previous.sampled_at
        if elapsed <= 0:
            return None
        delta_cpu_seconds = cpu_seconds - previous.cpu_seconds
        if delta_cpu_seconds < 0:
            return None
        return delta_cpu_seconds / elapsed * 100

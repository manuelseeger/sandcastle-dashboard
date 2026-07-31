"""Unit tests for host-capacity reads used to scale resource bars."""

from __future__ import annotations

from sandcastle_dashboard import system_resources


def test_cpu_count_returns_a_positive_integer():
    assert system_resources.cpu_count() >= 1


def test_cpu_count_falls_back_to_one_when_undetectable(monkeypatch):
    monkeypatch.setattr(system_resources.os, "cpu_count", lambda: None)

    assert system_resources.cpu_count() == 1


def test_total_memory_bytes_multiplies_pages_by_page_size(monkeypatch):
    monkeypatch.setattr(
        system_resources.os,
        "sysconf",
        lambda name: {"SC_PHYS_PAGES": 1000, "SC_PAGE_SIZE": 4096}[name],
    )

    assert system_resources.total_memory_bytes() == 1000 * 4096


def test_total_memory_bytes_returns_zero_when_unsupported(monkeypatch):
    def _raise(name):
        raise OSError("not supported")

    monkeypatch.setattr(system_resources.os, "sysconf", _raise)

    assert system_resources.total_memory_bytes() == 0

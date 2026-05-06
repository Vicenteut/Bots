import json
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from json_store import read_json, write_json, append_to_json_list


@pytest.fixture
def tmp_json(tmp_path):
    return tmp_path / "test.json"


def test_write_and_read_roundtrip(tmp_json):
    write_json(tmp_json, {"key": "value", "num": 42})
    assert read_json(tmp_json) == {"key": "value", "num": 42}


def test_read_missing_file_returns_default(tmp_json):
    assert read_json(tmp_json, default={"empty": True}) == {"empty": True}


def test_read_missing_file_returns_none_by_default(tmp_json):
    assert read_json(tmp_json) is None


def test_write_is_atomic_on_crash(tmp_json):
    write_json(tmp_json, {"original": True})
    tmp = tmp_json.parent / f".tmp_{tmp_json.name}"
    tmp.write_text("{ INVALID JSON", encoding="utf-8")
    assert read_json(tmp_json) == {"original": True}


def test_append_to_json_list(tmp_json):
    append_to_json_list(tmp_json, {"a": 1})
    append_to_json_list(tmp_json, {"b": 2})
    assert read_json(tmp_json, default=[]) == [{"a": 1}, {"b": 2}]


def test_append_creates_file_if_missing(tmp_json):
    append_to_json_list(tmp_json, {"first": True})
    assert read_json(tmp_json, default=[]) == [{"first": True}]


def test_concurrent_appends_no_data_loss(tmp_json):
    errors = []

    def appender(n):
        try:
            for i in range(5):
                append_to_json_list(tmp_json, {"thread": n, "i": i})
                time.sleep(0.001)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=appender, args=(t,)) for t in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Errors in threads: {errors}"
    result = read_json(tmp_json, default=[])
    assert len(result) == 20, f"Expected 20 entries, got {len(result)}"


def test_concurrent_writes_no_corruption(tmp_json):
    errors = []

    def writer(val):
        try:
            for _ in range(10):
                write_json(tmp_json, {"value": val})
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    result = read_json(tmp_json)
    assert isinstance(result, dict)
    assert "value" in result

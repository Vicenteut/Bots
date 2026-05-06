import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from publish_service import (
    extract_threads_result,
    classify_publish_result,
    media_kind,
)


def test_extract_threads_result_parses_success():
    output = 'some log\n[THREADS_RESULT]{"post_id": "123", "success": true}\nmore log'
    result = extract_threads_result(output)
    assert result == {"post_id": "123", "success": True}


def test_extract_threads_result_returns_empty_on_missing():
    assert extract_threads_result("no result line here") == {}


def test_extract_threads_result_returns_empty_on_invalid_json():
    assert extract_threads_result("[THREADS_RESULT]{INVALID}") == {}


def test_classify_success():
    output = '[THREADS_RESULT]{"post_id": "456", "success": true}'
    result = classify_publish_result(output, returncode=0, media_kind_str="text")
    assert result["success"] is True
    assert result["post_id"] == "456"
    assert result["status"] == "OK"
    assert result["error_category"] is None


def test_classify_auth_error():
    output = "some log\n[ERROR] token invalid — unauthorized\n"
    result = classify_publish_result(output, returncode=1, media_kind_str="text")
    assert result["success"] is False
    assert result["error_category"] == "AUTH_ERROR"


def test_classify_media_error():
    output = "[ERROR] no valid image found in container"
    result = classify_publish_result(output, returncode=1, media_kind_str="image")
    assert result["error_category"] == "MEDIA_ERROR"


def test_classify_timeout():
    output = "connection timed out"
    result = classify_publish_result(output, returncode=1, media_kind_str="text")
    assert result["error_category"] == "TIMEOUT"


def test_classify_meta_error():
    output = "[META ERROR] fbtrace_id: abc123"
    result = classify_publish_result(output, returncode=1, media_kind_str="text")
    assert result["error_category"] == "META_ERROR"


def test_classify_generic_failure():
    output = "something went wrong"
    result = classify_publish_result(output, returncode=1, media_kind_str="text")
    assert result["success"] is False
    assert result["error_category"] == "FAILED"


def test_media_kind_video():
    assert media_kind("video", ["/tmp/vid.mp4"]) == "video"


def test_media_kind_carousel():
    assert media_kind("image", ["/tmp/a.jpg", "/tmp/b.jpg"]) == "carousel"


def test_media_kind_single_image():
    assert media_kind("image", ["/tmp/a.jpg"]) == "image"


def test_media_kind_text():
    assert media_kind("image", []) == "text"

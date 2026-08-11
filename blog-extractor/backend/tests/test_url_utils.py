import pytest

from app.services.url_utils import (
    normalize_url, get_domain, is_same_site, validate_public_url,
    UnsafeURLError, looks_like_non_blog_path,
)


def test_normalize_strips_trailing_slash():
    assert normalize_url("https://example.com/blog/test/") == normalize_url("https://example.com/blog/test")


def test_normalize_strips_www_and_tracking_params():
    a = normalize_url("https://www.example.com/blog/test?utm_source=fb&id=1")
    b = normalize_url("https://example.com/blog/test?id=1")
    assert a == b


def test_normalize_preserves_root_slash():
    assert normalize_url("https://example.com") == normalize_url("https://example.com/")


def test_get_domain_strips_www():
    assert get_domain("https://www.example.com/blog") == "example.com"


def test_is_same_site_subdomain():
    assert is_same_site("https://blog.example.com/post", "example.com")
    assert not is_same_site("https://other.com/post", "example.com")


@pytest.mark.parametrize("url", [
    "http://localhost/blog",
    "http://127.0.0.1/blog",
    "http://0.0.0.0/blog",
    "http://169.254.169.254/latest/meta-data",  # cloud metadata endpoint
    "ftp://example.com/blog",
])
def test_validate_public_url_rejects_unsafe(url):
    with pytest.raises(UnsafeURLError):
        validate_public_url(url)


def test_looks_like_non_blog_path():
    assert looks_like_non_blog_path("https://example.com/login")
    assert looks_like_non_blog_path("https://example.com/cart")
    assert looks_like_non_blog_path("https://example.com/")
    assert not looks_like_non_blog_path("https://example.com/blog/my-great-article")

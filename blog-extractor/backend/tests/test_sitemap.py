from app.services.sitemap import _parse_sitemap_xml

URLSET_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/blog/post-1</loc><lastmod>2026-01-01</lastmod></url>
  <url><loc>https://example.com/blog/post-2</loc></url>
</urlset>"""

SITEMAP_INDEX_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example.com/post-sitemap.xml</loc></sitemap>
  <sitemap><loc>https://example.com/page-sitemap.xml</loc></sitemap>
</sitemapindex>"""


def test_parse_urlset():
    children, pages = _parse_sitemap_xml(URLSET_XML)
    assert children == []
    assert len(pages) == 2
    assert pages[0]["url"] == "https://example.com/blog/post-1"
    assert pages[0]["lastmod"] == "2026-01-01"
    assert pages[1]["lastmod"] is None


def test_parse_sitemap_index():
    children, pages = _parse_sitemap_xml(SITEMAP_INDEX_XML)
    assert pages == []
    assert len(children) == 2
    assert "post-sitemap.xml" in children[0]


def test_parse_malformed_xml_returns_empty():
    children, pages = _parse_sitemap_xml(b"not xml at all <<<")
    assert children == []
    assert pages == []

from app.services.extractor import extract_article

SAMPLE_HTML = """
<html><head>
<title>How AI Works | Example Blog</title>
<meta name="description" content="A deep dive into AI.">
<link rel="canonical" href="https://example.com/blog/how-ai-works">
<meta property="og:image" content="https://example.com/img.png">
<script type="application/ld+json">
{"@type": "BlogPosting", "headline": "How AI Works", "datePublished": "2026-01-05",
 "author": {"name": "Jane Doe", "url": "https://example.com/authors/jane"},
 "keywords": "AI, Machine Learning"}
</script>
</head>
<body>
<nav><a href="/">Home</a><a href="/blog">Blog</a></nav>
<header>Site Header</header>
<article>
<h1>How AI Works</h1>
<p>This introduction paragraph explains what the reader will learn in this piece.</p>
<h2>What Is AI?</h2>
<p>AI is a broad field of computer science focused on building smart systems that act.</p>
<h2>Benefits of AI</h2>
<h3>Efficiency</h3>
<p>AI systems can process huge volumes of data far faster than humans manually could.</p>
<h3>Accuracy</h3>
<p>Well-trained models can outperform humans on narrow, well-defined tasks reliably.</p>
<h2>Frequently Asked Questions</h2>
<p>Is AI dangerous? Not inherently -- risk depends heavily on how systems are deployed.</p>
<h2>Conclusion</h2>
<p>AI is a powerful tool, and understanding its basics matters for everyone today.</p>
</article>
<aside class="sidebar">Related posts here</aside>
<footer>Site Footer</footer>
</body></html>
"""


def test_extracts_metadata():
    a = extract_article(SAMPLE_HTML, "https://example.com/blog/how-ai-works")
    assert a.title == "How AI Works"
    assert a.author == "Jane Doe"
    assert a.author_url == "https://example.com/authors/jane"
    assert a.published_date == "2026-01-05"
    assert "AI" in a.tags
    assert a.canonical_url == "https://example.com/blog/how-ai-works"
    assert a.featured_image == "https://example.com/img.png"


def test_extracts_headings_in_order():
    a = extract_article(SAMPLE_HTML, "https://example.com/blog/how-ai-works")
    assert a.h2_headings == ["What Is AI?", "Benefits of AI", "Frequently Asked Questions", "Conclusion"]
    assert a.h3_headings == ["Efficiency", "Accuracy"]


def test_excludes_nav_and_footer_noise():
    a = extract_article(SAMPLE_HTML, "https://example.com/blog/how-ai-works")
    assert "Site Header" not in a.structured_content
    assert "Site Footer" not in a.structured_content
    assert "Related posts" not in a.structured_content


def test_splits_faq_and_conclusion():
    a = extract_article(SAMPLE_HTML, "https://example.com/blog/how-ai-works")
    assert "Is AI dangerous" in a.faq_content
    assert "powerful tool" in a.conclusion


def test_quality_flag_on_thin_content():
    thin_html = "<html><body><article><h1>Empty</h1></article></body></html>"
    a = extract_article(thin_html, "https://example.com/blog/empty")
    assert a.quality_ok is False

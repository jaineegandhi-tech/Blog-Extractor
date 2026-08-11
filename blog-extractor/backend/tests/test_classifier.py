from app.services.classifier import url_looks_like_blog, classify_page_content

ARTICLE_HTML = """
<html><head>
<script type="application/ld+json">{"@type": "BlogPosting", "headline": "Test"}</script>
<meta property="og:type" content="article">
</head>
<body>
<article>
<h1>A Great Article</h1>
<p>This is a long enough paragraph to count as real body content for our heuristic.</p>
<h2>Section One</h2>
<p>Another paragraph with plenty of words so the density heuristic picks it up nicely.</p>
<h2>Section Two</h2>
<p>Yet another paragraph, again long enough, discussing things in reasonable depth here.</p>
</article>
</body></html>
"""

LOGIN_HTML = """
<html><head><title>Login</title></head>
<body><form><input name="user"><input name="pass"></form></body></html>
"""


def test_url_heuristic():
    assert url_looks_like_blog("https://example.com/blog/my-post")
    assert not url_looks_like_blog("https://example.com/login")
    assert not url_looks_like_blog("https://example.com/cart")


def test_content_classifier_identifies_article():
    is_blog, confidence = classify_page_content(ARTICLE_HTML, "https://example.com/blog/my-post")
    assert is_blog is True
    assert confidence > 0.55


def test_content_classifier_rejects_login_even_with_blog_like_url():
    is_blog, confidence = classify_page_content(LOGIN_HTML, "https://example.com/blog/login")
    assert is_blog is False

from __future__ import annotations

import time

import httpx
import pytest
import respx

from app import net
from app.pipeline import crawl
from app.pipeline.crawl import Crawler, select_pages

PUBLIC_IP = "93.184.216.34"

HOME = """<!doctype html><html><head><title>Reilly Plumbing</title></head><body>
<nav>
  <a href="/">Home</a>
  <a href="/services/drain-cleaning">Drain cleaning</a>
  <a href="/about-us/">About Us</a>
  <a href="https://reillyplumbing.com/contact">Contact</a>
  <a href="/our-team">Meet the plumbers</a>
  <a href="/files/brochure.pdf">About (PDF)</a>
  <a href="https://facebook.com/reillyplumbing">Facebook</a>
  <a href="mailto:office@reillyplumbing.com">Email us</a>
  <a href="#top">Top</a>
</nav>
<main><p>Family owned since 1979. Serving Columbus with honest plumbing.</p></main>
<footer>&copy; 2018 Reilly Plumbing Co.</footer>
</body></html>"""

PAGE = "<html><body><h1>{}</h1><p>" + "Lorem ipsum dolor sit amet. " * 20 + "</p></body></html>"


@pytest.fixture(autouse=True)
def _fake_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never hit real DNS. `intranet.*` resolves privately; everything else is public."""

    async def resolve(host: str) -> list[str]:
        if host.startswith("intranet."):
            return ["10.0.0.5"]
        if host == "metadata.test":
            return ["169.254.169.254"]
        return [PUBLIC_IP]

    monkeypatch.setattr(net, "resolve", resolve)


def html(body: str, status: int = 200) -> httpx.Response:
    return httpx.Response(status, text=body, headers={"content-type": "text/html; charset=utf-8"})


# ---------------------------------------------------------------- page selection


def test_page_selection_picks_about_team_contact() -> None:
    picked = select_pages(HOME, "https://reillyplumbing.com/")
    assert picked == [
        ("about", "https://reillyplumbing.com/about-us/"),
        ("team", "https://reillyplumbing.com/our-team"),
        ("contact", "https://reillyplumbing.com/contact"),
    ]


def test_page_selection_uses_anchor_text_and_caps_at_three() -> None:
    home = """<a href="/p/1">Our Story</a><a href="/p/2">Careers</a><a href="/p/3">Contact</a>
              <a href="/p/4">Staff</a><a href="https://other.com/about">About</a>"""
    picked = select_pages(home, "https://x.com/")
    assert [k for k, _ in picked] == ["about", "team", "contact"]
    assert all(u.startswith("https://x.com/") for _, u in picked)


# ---------------------------------------------------------------- SSRF guard


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.1.2.3/",
        "http://192.168.0.10/admin",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://localhost:8000/",
        "http://intranet.acme-corp.com/",
        "http://metadata.test/",
        "file:///etc/passwd",
        "ftp://example.com/",
        "gopher://example.com/",
    ],
)
async def test_ssrf_guard_blocks_non_public_targets(url: str) -> None:
    with pytest.raises(net.BlockedURL):
        await net.assert_public_url(url)


async def test_ssrf_guard_allows_public_host() -> None:
    await net.assert_public_url("https://reillyplumbing.com/about")


@respx.mock
async def test_crawl_never_contacts_private_host() -> None:
    route = respx.route(host="intranet.acme-corp.com")
    async with Crawler(per_host_interval=0) as c:
        res = await c.crawl("http://intranet.acme-corp.com/", use_cache=False)
    assert res.status == "unreachable" and "blocked" in (res.error or "")
    assert not route.called


@respx.mock
async def test_redirect_to_private_ip_is_blocked() -> None:
    respx.get("https://evil-redirect.com/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://evil-redirect.com/").mock(
        return_value=httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})
    )
    metadata = respx.route(host="169.254.169.254")
    async with Crawler(per_host_interval=0) as c:
        res = await c.crawl("https://evil-redirect.com/", use_cache=False)
    assert res.status == "unreachable"
    assert not metadata.called


# ---------------------------------------------------------------- robots


@respx.mock
async def test_robots_full_disallow_is_honoured() -> None:
    respx.get("https://blocked-hvac.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /\n")
    )
    home = respx.get("https://blocked-hvac.com/").mock(return_value=html(HOME))
    async with Crawler(per_host_interval=0) as c:
        res = await c.crawl("https://blocked-hvac.com/", use_cache=False)
    assert res.status == "blocked_robots"
    assert res.pages == []
    assert not home.called


@respx.mock
async def test_robots_partial_disallow_skips_path_and_marks_partial() -> None:
    respx.get("https://reillyplumbing.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: BuyBuildScoreBot\nDisallow: /our-team\n")
    )
    respx.get("https://reillyplumbing.com/").mock(return_value=html(HOME))
    respx.get("https://reillyplumbing.com/about-us/").mock(return_value=html(PAGE.format("About")))
    respx.get("https://reillyplumbing.com/contact").mock(return_value=html(PAGE.format("Contact")))
    team = respx.get("https://reillyplumbing.com/our-team").mock(return_value=html(PAGE.format("Team")))
    async with Crawler(per_host_interval=0) as c:
        res = await c.crawl("https://reillyplumbing.com/", use_cache=False)
    assert res.status == "partial"
    assert [p.kind for p in res.pages] == ["home", "about", "contact"]
    assert res.skipped_by_robots == ["https://reillyplumbing.com/our-team"]
    assert not team.called
    assert res.final_scheme == "https" and res.tls_ok is True
    sent_ua = respx.calls[0].request.headers["user-agent"]
    assert sent_ua.startswith("BuyBuildScoreBot/")


@respx.mock
async def test_robots_of_the_redirect_target_govern_subpages() -> None:
    respx.get("https://old-name.com/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://old-name.com/").mock(
        return_value=httpx.Response(301, headers={"location": "https://new-name.com/"})
    )
    respx.get("https://new-name.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /\n")
    )
    respx.get("https://new-name.com/").mock(return_value=html(HOME))
    about = respx.route(host="new-name.com", path__startswith="/about")
    async with Crawler(per_host_interval=0) as c:
        res = await c.crawl("https://old-name.com/", use_cache=False)
    assert res.status == "partial" and len(res.pages) == 1
    assert not about.called


@respx.mock
async def test_robots_5xx_means_do_not_crawl() -> None:
    respx.get("https://flaky.com/robots.txt").mock(return_value=httpx.Response(503))
    home = respx.get("https://flaky.com/").mock(return_value=html(HOME))
    async with Crawler(per_host_interval=0) as c:
        res = await c.crawl("https://flaky.com/", use_cache=False)
    assert res.status == "blocked_robots" and not home.called


# ---------------------------------------------------------------- fetching behaviour


@respx.mock
async def test_full_crawl_ok_caches_and_reuses(monkeypatch: pytest.MonkeyPatch) -> None:
    respx.get("http://reillyplumbing.com/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("http://reillyplumbing.com/").mock(return_value=html(HOME))
    for path in ("about-us/", "our-team"):
        respx.get(f"http://reillyplumbing.com/{path}").mock(return_value=html(PAGE.format(path)))
    # absolute link on the page points at https
    respx.get("https://reillyplumbing.com/contact").mock(return_value=html(PAGE.format("contact")))
    async with Crawler(per_host_interval=0) as c:
        res = await c.crawl("http://reillyplumbing.com", use_cache=True)
        assert res.status == "ok" and len(res.pages) == 4
        assert res.final_scheme == "http" and res.tls_ok is None
        assert res.home is not None and "Family owned since 1979" in res.home.html
        calls = len(respx.calls)
        again = await c.crawl("http://reillyplumbing.com", use_cache=True)
    assert again.cached and len(again.pages) == 4 and again.home is not None
    assert again.home.html == res.home.html
    assert len(respx.calls) == calls  # served from cache, no new requests


@respx.mock
async def test_time_budget_keeps_pages_already_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """A slow subpage must not erase the homepage we already read (live bug: 11 parallel sites)."""
    import asyncio

    monkeypatch.setattr(crawl, "DOMAIN_BUDGET_S", 0.5)
    respx.get("https://slowsub.com/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://slowsub.com/").mock(
        return_value=html(HOME.replace("reillyplumbing.com", "slowsub.com"))
    )

    async def slow(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return html(PAGE.format("late"))

    respx.route(host="slowsub.com").mock(side_effect=slow)
    async with Crawler(per_host_interval=0) as c:
        res = await c.crawl("https://slowsub.com/", use_cache=False)
    assert res.status == "partial" and [p.kind for p in res.pages] == ["home"]
    assert "time budget" in (res.error or "")


async def test_unexpected_crawl_error_becomes_unreachable_not_a_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Live bug: an exception that isn't an httpx.HTTPError dropped the company from the run."""

    async def boom(self: Crawler, result: crawl.CrawlResult) -> crawl.CrawlResult:
        raise ValueError("weird")

    monkeypatch.setattr(Crawler, "_crawl", boom)
    async with Crawler(per_host_interval=0) as c:
        res = await c.crawl("https://anything.com/", use_cache=False)
    assert res.status == "unreachable" and res.error == "ValueError" and res.pages == []


async def test_website_with_control_characters_is_cleaned_before_crawling() -> None:
    async with Crawler(per_host_interval=0) as c:
        res = await c.crawl("\n", use_cache=False)
    assert res.status == "no_site"


@respx.mock
async def test_slow_homepage_is_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    monkeypatch.setattr(crawl, "DOMAIN_BUDGET_S", 0.3)
    respx.get("https://slowhome.com/robots.txt").mock(return_value=httpx.Response(404))

    async def slow(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return html("<p>late</p>")

    respx.get("https://slowhome.com/").mock(side_effect=slow)
    async with Crawler(per_host_interval=0) as c:
        res = await c.crawl("https://slowhome.com/", use_cache=False)
    assert res.status == "unreachable" and res.pages == [] and res.error == "timeout"


@respx.mock
async def test_retries_on_503_then_succeeds() -> None:
    respx.get("https://retry.com/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://retry.com/").mock(side_effect=[httpx.Response(503), html("<p>ok</p>")])
    async with Crawler(per_host_interval=0) as c:
        res = await c.crawl("https://retry.com/", use_cache=False)
    assert res.status == "ok"


@respx.mock
async def test_non_html_homepage_is_unreachable() -> None:
    respx.get("https://pdfsite.com/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://pdfsite.com/").mock(
        return_value=httpx.Response(200, content=b"%PDF", headers={"content-type": "application/pdf"})
    )
    async with Crawler(per_host_interval=0) as c:
        res = await c.crawl("https://pdfsite.com/", use_cache=False)
    assert res.status == "unreachable"


@respx.mock
async def test_bad_certificate_falls_back_to_http_and_records_tls() -> None:
    import ssl

    respx.get("https://badcert.com/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://badcert.com/").mock(
        side_effect=httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED]", request=None)  # type: ignore[arg-type]
    )
    respx.get("http://badcert.com/").mock(return_value=html("<p>still here</p>"))
    del ssl
    async with Crawler(per_host_interval=0) as c:
        res = await c.crawl("https://badcert.com/", use_cache=False)
    assert res.status == "ok" and res.tls_ok is False and res.final_scheme == "http"


def test_no_site() -> None:
    import asyncio

    async def run() -> crawl.CrawlResult:
        async with Crawler(per_host_interval=0) as c:
            return await c.crawl(None)

    assert asyncio.run(run()).status == "no_site"


async def test_host_throttle_spaces_requests() -> None:
    t = net.HostThrottle(0.2)
    start = time.monotonic()
    for _ in range(3):
        await t.wait("a.com")
    assert time.monotonic() - start >= 0.38


def test_slim_html_drops_bulk_but_keeps_scripts() -> None:
    raw = (
        "<style>body{}</style><svg><path/></svg><!-- hi -->"
        '<script src="https://code.tidio.co/abc.js"></script><p>x</p>'
    )
    slim = crawl.slim_html(raw)
    assert "tidio" in slim and "<style" not in slim and "<svg" not in slim and "hi" not in slim

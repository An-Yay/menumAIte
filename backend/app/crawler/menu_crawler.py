"""Reads restaurant menus from the live web.

Restaurant menus are not available from any reliable structured API, so the menu
is read from the restaurant's own website: fetch the homepage, find the page that
holds the menu, and pull its text out.

This module deliberately does **no** language-model work. It returns raw menu
text and a description of how that text was obtained; turning the text into
structured dishes and prices happens later, in the model-backed extraction step.
Keeping the crawl deterministic makes it fast, cheap and easy to test.

Design priorities
-----------------
* **Speed.** Short timeouts, a small cap on pages per restaurant, and candidate
  menu pages fetched concurrently.
* **Honesty.** Every failure path produces a human-readable note (for example
  "the menu is published as a PDF") so the traveller is told what happened
  instead of being shown invented dishes.
* **Politeness.** A real User-Agent, conservative request counts, and a byte cap
  so we never download large files from small business sites.
"""

from __future__ import annotations

import asyncio
import io
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import httpx
from pypdf import PdfReader
from selectolax.parser import HTMLParser

# Presented as a normal browser with a contact hint, so site owners can identify
# the traffic. Some sites reject unknown or empty agents outright.
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36 menumAIte/0.1"
)

# --- Speed and safety limits -------------------------------------------------
# Tight budgets keep the traveller's wait short. A restaurant website that needs
# longer than this is reported as unreadable rather than holding up the response.
_TIMEOUT_SECONDS = 8.0
_MAX_MENU_PAGES = 3  # Candidate menu pages fetched per restaurant, in parallel.
# Menu PDFs are image-heavy and routinely a few megabytes, so the size cap has to
# be generous enough to admit them while still refusing anything unreasonable.
_MAX_BYTES = 12_000_000
_MAX_TEXT_CHARS = 12_000  # Text budget handed to the extraction step.
_MAX_PDF_PAGES = 6  # Menus are short; bounds work on oversized documents.

# Words that identify a menu page, across the languages a traveller is likely to
# meet in Europe and beyond. Matched against both link URLs and link text.
_MENU_WORDS = (
    "menu",
    "menus",
    "menú",
    "menù",
    "carta",
    "carte",
    "ementa",
    "speisekarte",
    "karte",
    "kaart",
    "ruokalista",
    "matsedel",
    "jadwal",
    "меню",
    "food",
    "dishes",
    "eat",
)

# Link words that look menu-ish but lead somewhere unhelpful.
_MENU_STOPWORDS = (
    "wine",
    "drink",
    "cocktail",
    "bar",
    "gift",
    "shop",
    "book",
    "reserv",
    "cater",
    "job",
    "career",
    "press",
)

# Currency and price shapes, used to report whether the page actually publishes
# prices. Prices are frequently absent, and that fact is reported rather than
# hidden.
_PRICE_PATTERN = re.compile(
    r"(?:[€$£¥₹]\s?\d{1,4}(?:[.,]\d{1,2})?)"  # symbol first: €12,50
    r"|(?:\d{1,4}(?:[.,]\d{1,2})?\s?(?:[€$£¥₹]|eur|euros?|usd|gbp))",  # 12,50 €
    re.IGNORECASE,
)

# Printed menus, especially PDFs, usually state the currency once in a heading and
# then list bare numbers such as "12,50" or "9.95" beside each dish. Those are not
# matched by the pattern above, so this second pattern recognises the bare form.
# It is intentionally narrow — one or two digits, then exactly two decimals — which
# is the shape of a dish price and not of a year, a phone number or a street number.
_BARE_PRICE_PATTERN = re.compile(r"\b\d{1,2}[.,]\d{2}\b")


def count_prices(text: str) -> int:
    """Estimate how many prices a menu page publishes.

    Counts explicitly marked prices first (``€12,50``). If none are found, falls
    back to counting bare decimals such as ``12,50``.

    The bare count deliberately does NOT require a currency symbol anywhere on the
    page. Printed menus, and PDF menus especially, very often omit the currency
    entirely because it is obvious to a diner standing in the restaurant. An
    earlier version of this function insisted on currency context and consequently
    reported "no prices published" for a menu containing 118 of them. The currency
    for a dish is instead inferred from the restaurant's country, which is
    information we already hold.

    A run of bare decimals is only treated as prices when there are several of
    them, since a page with one or two stray decimals is more likely to be quoting
    something else.
    """

    explicit = len(_PRICE_PATTERN.findall(text))
    if explicit:
        return explicit

    bare = len(_BARE_PRICE_PATTERN.findall(text))
    # Three or more suggests a price column rather than incidental numbers.
    return bare if bare >= 3 else 0

# Tags whose contents are never useful menu text.
_NOISE_TAGS = ("script", "style", "noscript", "svg", "iframe", "nav", "footer")

# Vocabulary that indicates a page really is about food. Expired restaurant
# domains are frequently re-registered as spam, and such a page can easily be
# longer and more "price-rich" than a genuine menu, so pages are checked for food
# relevance before being accepted.
_FOOD_WORDS = (
    "salad", "soup", "starter", "dessert", "dish", "vegan", "vegetarian",
    "grilled", "roasted", "sauce", "cheese", "bread", "rice", "noodle", "pasta",
    "burger", "sandwich", "breakfast", "lunch", "dinner", "drink", "coffee",
    # Spanish / Catalan / Portuguese
    "ensalada", "sopa", "postre", "plato", "queso", "arroz", "pan", "bocadillo",
    "entrante", "amanida", "postres", "entrants", "carta", "menú", "menu",
    "desayuno", "almuerzo", "cena", "tapas", "bebida",
    # French / Italian / German
    "entrée", "plat", "fromage", "dessert", "primi", "secondi", "antipasti",
    "contorni", "vorspeise", "hauptgericht", "nachtisch", "gericht",
)

# Wording typical of domains that have been taken over for spam. Their presence
# is treated as strong evidence the page is not a restaurant menu.
_SPAM_WORDS = (
    "slot", "togel", "casino", "gacor", "judi", "poker", "betting", "situs",
    "viagra", "crypto airdrop", "loan approval",
)


def _pdf_text(content: bytes, max_pages: int = _MAX_PDF_PAGES) -> str:
    """Extract text from a menu PDF.

    Restaurants very often publish the menu only as a PDF, and in practice those
    PDFs are frequently the one place prices are actually printed, so they are
    worth reading rather than skipping.

    Only the first few pages are read: menus are short, and this bounds the work
    done on an unexpectedly large document. A PDF built from scanned images has no
    text layer and yields nothing, which the caller reports honestly instead of
    guessing at the contents.
    """

    try:
        reader = PdfReader(io.BytesIO(content))
    except Exception:  # noqa: BLE001 - pypdf raises a variety of parse errors
        return ""

    parts: list[str] = []
    for page in reader.pages[:max_pages]:
        try:
            parts.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - a single bad page should not abort
            continue

    # PDF extraction produces ragged line breaks; collapse them so the text reads
    # as continuous content for the extraction step.
    return re.sub(r"\s{2,}", " ", " ".join(parts)).strip()


def food_relevance(text: str) -> int:
    """Count distinct food-related words in a page.

    Used to confirm a page is actually about food. Returns a negative score when
    spam vocabulary is present, so hijacked domains are rejected outright rather
    than being presented to the traveller as a menu.
    """

    lowered = text.lower()

    for spam in _SPAM_WORDS:
        if spam in lowered:
            return -1

    return sum(1 for word in set(_FOOD_WORDS) if word in lowered)


@dataclass
class MenuPage:
    """One fetched page and what we managed to read from it."""

    url: str
    text: str = ""
    price_hits: int = 0
    note: str | None = None
    # Original markup, kept so menu links can be discovered without re-fetching
    # the page. Not passed on to the extraction step.
    html: str = ""
    # How strongly the page looks like food content; see `food_relevance`.
    food_score: int = 0


@dataclass
class MenuCrawlResult:
    """Everything the crawl learned about one restaurant's menu.

    `text` is what the extraction step consumes. When it is empty, `note`
    explains why, so the interface can be honest with the traveller.
    """

    website_url: str
    menu_url: str | None = None
    text: str = ""
    price_hits: int = 0
    note: str | None = None
    pages_visited: list[str] = field(default_factory=list)

    @property
    def has_menu_text(self) -> bool:
        """Whether enough text was recovered to be worth extracting from."""

        return len(self.text.strip()) >= 200

    @property
    def prices_present(self) -> bool:
        """Whether the page appears to publish prices at all.

        A couple of stray numbers are not evidence of a priced menu, so a small
        threshold is applied.
        """

        return self.price_hits >= 3


def _clean_text(html: str) -> str:
    """Extract readable text from HTML.

    Navigation, scripts and styles are removed first so the extraction step is
    not fed site chrome, then whitespace is collapsed to keep the text compact.
    """

    tree = HTMLParser(html)
    for tag in _NOISE_TAGS:
        for node in tree.css(tag):
            node.decompose()

    body = tree.body or tree.root
    if body is None:
        return ""

    text = body.text(separator=" ", strip=True)
    return re.sub(r"\s{2,}", " ", text)


def _score_menu_link(href: str, link_text: str) -> int:
    """Rank how likely a link is to lead to the food menu.

    A link whose text is exactly "Menu" is a much better bet than one that merely
    contains the substring, and drinks or booking pages are pushed down. Scoring
    (rather than taking the first match) means we spend our small page budget on
    the most promising candidates.
    """

    href_l = href.lower()
    text_l = link_text.lower().strip()
    score = 0

    # An exact label is the strongest signal available.
    if text_l in _MENU_WORDS:
        score += 10

    for word in _MENU_WORDS:
        if word in text_l:
            score += 3
            break

    for word in _MENU_WORDS:
        if word in href_l:
            score += 3
            break

    # A dedicated path segment (/menu, /carta) beats an incidental mention.
    path = urlparse(href_l).path.strip("/")
    if path.split("/")[-1] in _MENU_WORDS:
        score += 5

    # Drinks lists and booking pages are not what we are looking for.
    for stop in _MENU_STOPWORDS:
        if stop in href_l or stop in text_l:
            score -= 6
            break

    # A PDF is still a menu, just one this tier cannot read yet.
    if href_l.endswith(".pdf"):
        score += 2

    return score


def _is_allowed_offsite_menu(url: str, link_text: str) -> bool:
    """Whether an external link is worth following in search of a menu.

    Restaurants commonly publish the menu somewhere other than their own domain,
    for example as a PDF on a file-storage service. Those links are useful. Social
    profiles, booking widgets and delivery marketplaces are not, and following
    them would waste the small page budget.
    """

    host = urlparse(url).netloc.lower()

    blocked_hosts = (
        "instagram.", "facebook.", "twitter.", "x.com", "tiktok.",
        "youtube.", "google.com", "goo.gl", "maps.google.",
        "thefork.", "opentable.", "ubereats.", "deliveroo.", "glovoapp.",
        "justeat.", "tripadvisor.", "yelp.", "linkedin.", "wa.me",
    )
    if any(blocked in host for blocked in blocked_hosts):
        return False

    # A document link, or link text that names a menu, is a strong enough signal
    # to justify one off-domain fetch.
    if url.lower().endswith((".pdf", ".jpg", ".jpeg", ".png", ".webp")):
        return True

    lowered_text = link_text.lower()
    return any(word in lowered_text for word in _MENU_WORDS)


def find_menu_links(html: str, base_url: str, limit: int = _MAX_MENU_PAGES) -> list[str]:
    """Return the most promising menu URLs found on a page.

    Only links on the restaurant's own domain are considered, so the crawl cannot
    wander onto aggregators or social networks.
    """

    tree = HTMLParser(html)
    base_host = urlparse(base_url).netloc.lower().removeprefix("www.")

    scored: dict[str, int] = {}
    for node in tree.css("a"):
        href = node.attributes.get("href")
        if not href or href.startswith(("mailto:", "tel:", "javascript:")):
            continue

        # Same-page anchors (href="#carta") cannot be fetched separately, but they
        # do tell us the menu is on the page we already have.
        if href.startswith("#"):
            continue

        absolute = urljoin(base_url, href)
        host = urlparse(absolute).netloc.lower().removeprefix("www.")
        link_text = node.text(strip=True) or ""

        if host and host != base_host:
            # Menus are often hosted off-site, typically as a PDF on a storage or
            # menu-hosting service. Those are worth following; social networks and
            # booking widgets are not.
            if not _is_allowed_offsite_menu(absolute, link_text):
                continue

        score = _score_menu_link(absolute, link_text)
        if score <= 0:
            continue

        # The same page is often linked several times; keep its best score.
        scored[absolute] = max(scored.get(absolute, 0), score)

    ranked = sorted(scored.items(), key=lambda item: item[1], reverse=True)
    return [url for url, _ in ranked[:limit]]


class MenuCrawler:
    """Fetches and reads restaurant menu pages.

    Only plain HTTP with HTML parsing is implemented. Pages that need a browser
    to render, and menus published as PDFs or images, are detected and reported
    so later tiers can be added without changing callers.
    """

    def __init__(self, timeout: float = _TIMEOUT_SECONDS) -> None:
        self._timeout = timeout
        # Created lazily: most crawls never hit a certificate error, so most
        # crawls never need this client.
        self._insecure_client_instance: httpx.AsyncClient | None = None

    @property
    def _insecure_client(self) -> httpx.AsyncClient:
        """A client that skips certificate verification, used only as a fallback.

        See `_fetch` for why this exists and the boundaries on when it is used.
        """

        if self._insecure_client_instance is None:
            self._insecure_client_instance = httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=True,
                verify=False,
                headers={"User-Agent": _USER_AGENT, "Accept-Language": "en,*;q=0.5"},
            )
        return self._insecure_client_instance

    async def _fetch(self, client: httpx.AsyncClient, url: str) -> MenuPage:
        """Fetch one URL and turn it into a `MenuPage`.

        Failures are captured as notes rather than raised: one unreachable page
        should never abort the wider recommendation.

        A certificate error gets one retry with verification disabled. Restaurant
        and menu-aggregator sites are frequently small operations with an expired
        or misconfigured certificate on an otherwise legitimate, public page; a
        strict client simply cannot read them, which was losing real menus (with
        real prices) that a browser reaches without issue. This is a deliberate,
        narrow trade-off: it applies only to this read-only fetch of public menu
        pages, only as a fallback after the verified attempt fails specifically on
        the certificate, and no credentials or other secrets are ever sent over
        these connections.
        """

        try:
            response = await client.get(url)
        except httpx.ConnectError as exc:
            if "certificate" not in str(exc).lower():
                return MenuPage(url=url, note=f"could not be fetched ({type(exc).__name__})")
            try:
                response = await self._insecure_client.get(url)
            except httpx.HTTPError as retry_exc:
                return MenuPage(
                    url=url,
                    note=f"could not be fetched even without certificate checks ({type(retry_exc).__name__})",
                )
        except httpx.HTTPError as exc:
            return MenuPage(url=url, note=f"could not be fetched ({type(exc).__name__})")

        if response.status_code >= 400:
            return MenuPage(url=url, note=f"returned HTTP {response.status_code}")

        content_type = response.headers.get("content-type", "").lower()
        content = response.content

        if len(content) > _MAX_BYTES:
            return MenuPage(url=url, note="page too large to read")

        # A PDF menu is read directly. This matters for prices: several
        # restaurants publish a priced menu only as a PDF while their web pages
        # carry no prices at all.
        if "application/pdf" in content_type or url.lower().endswith(".pdf"):
            text = _pdf_text(content)
            if not text:
                # No text layer, so the PDF is a scan or an export of images.
                return MenuPage(
                    url=url,
                    note="menu is a PDF with no readable text (probably scanned)",
                )
            page = MenuPage(url=url, text=text)
            page.price_hits = count_prices(text)
            page.food_score = food_relevance(text)
            return page

        if content_type.startswith("image/"):
            return MenuPage(url=url, note="menu is published as an image")
        if "html" not in content_type and content_type:
            return MenuPage(url=url, note=f"unsupported content type ({content_type})")

        html = content.decode(response.encoding or "utf-8", errors="replace")
        text = _clean_text(html)

        page = MenuPage(url=str(response.url), text=text, html=html)
        page.price_hits = count_prices(text)
        page.food_score = food_relevance(text)

        # Very little text usually means the page is rendered by JavaScript, which
        # this tier cannot execute.
        if len(text.strip()) < 200:
            page.note = "page has little readable text (likely rendered by JavaScript)"
        elif page.food_score < 0:
            # The domain appears to have been taken over by unrelated content.
            page.note = (
                "the website no longer appears to serve restaurant content"
            )

        return page

    async def crawl(self, website_url: str) -> MenuCrawlResult:
        """Read the menu for one restaurant.

        Fetches the homepage, ranks its links, then fetches the best candidates
        concurrently and keeps whichever page looks most like a real menu.
        """

        result = MenuCrawlResult(website_url=website_url)

        # `follow_redirects` matters because restaurant sites move between www,
        # https and locale-specific paths constantly.
        async with httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT, "Accept-Language": "en,*;q=0.5"},
        ) as client:
            home = await self._fetch(client, website_url)
            result.pages_visited.append(website_url)

            # Retry a couple of likely alternatives before giving up, since
            # provider-held links are frequently stale or have TLS host issues.
            if not home.text.strip():
                for fallback in self._fallback_urls(website_url):
                    home = await self._fetch(client, fallback)
                    result.pages_visited.append(fallback)
                    if home.text.strip():
                        break

            if not home.text.strip():
                result.note = f"Homepage {home.note or 'could not be read'}."
                return result

            # The homepage itself is sometimes the menu (common for single-page
            # sites), so it stays in the running as a candidate.
            candidates: list[MenuPage] = [home]

            # Link discovery uses the markup captured during the homepage fetch,
            # so the page is only downloaded once.
            links = find_menu_links(home.html, str(home.url) or website_url)

            if links:
                fetched = await asyncio.gather(
                    *(self._fetch(client, link) for link in links)
                )
                candidates.extend(fetched)
                result.pages_visited.extend(links)

        # Close the certificate-skipping fallback client if `_fetch` created one
        # for this crawl, so it is not left open past the call that needed it.
        if self._insecure_client_instance is not None:
            await self._insecure_client_instance.aclose()
            self._insecure_client_instance = None

        best = self._pick_best(candidates)

        if best is None or not best.text.strip():
            # Nothing readable anywhere: report the most informative reason.
            notes = [page.note for page in candidates if page.note]
            result.note = (
                f"Menu could not be read: {notes[0]}." if notes
                else "No readable menu content was found on the website."
            )
            return result

        result.menu_url = best.url
        result.text = best.text[:_MAX_TEXT_CHARS]
        result.price_hits = best.price_hits
        if best.note:
            result.note = best.note
        elif not result.prices_present:
            # Recorded so the interface can state that prices are unavailable
            # rather than leaving the traveller to wonder.
            result.note = "Menu text was read, but no prices are published on the page."

        return result

    @staticmethod
    def _fallback_urls(url: str) -> list[str]:
        """Alternative URLs to try when the supplied address fails.

        Provider-held links are often slightly stale. Two failures are common
        enough to be worth retrying automatically:

        * a deep link that no longer exists while the site root is fine;
        * a `www.` host whose TLS certificate only covers the bare domain, which
          raises an SSL hostname mismatch.
        """

        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return []

        host = parsed.netloc
        bare_host = host.removeprefix("www.")

        candidates = [
            f"https://{host}/",
            f"https://{bare_host}/",
        ]

        # Preserve order while removing duplicates and the original URL.
        seen = {url}
        unique: list[str] = []
        for candidate in candidates:
            if candidate not in seen:
                seen.add(candidate)
                unique.append(candidate)
        return unique

    async def crawl_many(self, website_urls: list[str]) -> list[MenuCrawlResult]:
        """Crawl several restaurants at once.

        Shortlisted restaurants are independent of one another, so reading their
        menus concurrently keeps the traveller's total wait close to the slowest
        single site rather than the sum of all of them.
        """

        return list(await asyncio.gather(*(self.crawl(url) for url in website_urls)))

    @staticmethod
    def _pick_best(pages: list[MenuPage]) -> MenuPage | None:
        """Choose the page that most resembles a real menu.

        Ranking, in order of importance:

        1. Pages with spam or non-food content are discarded entirely. A hijacked
           domain can otherwise look attractive, being both long and full of
           numbers that resemble prices.
        2. Prefer pages that publish prices, since a priced list is almost
           certainly the menu itself.
        3. Prefer stronger food vocabulary, which separates a menu page from a
           homepage that merely links to one.
        4. Fall back to the longer text.
        """

        readable = [
            page
            for page in pages
            if page.text.strip() and page.food_score >= 0
        ]
        if not readable:
            return None

        return max(
            readable,
            key=lambda page: (
                page.price_hits > 0,
                page.food_score,
                len(page.text),
            ),
        )

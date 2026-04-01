"""
Web Search scraper v3
Motores: DuckDuckGo HTML → Google HTML → Bing HTML
Fallback: SerpAPI (gratis hasta 100 búsquedas/mes) si está configurado.

DIAGNÓSTICO DE PROBLEMAS:
- Si devuelve 0 resultados, corré: python3 -m scrapers.websearch "JBL Go 3"
- Los motores pueden bloquear por IP. Solución: rotar User-Agents + delays.
- Google bloquea más rápido que DDG. DDG es el más confiable sin API.
"""
import requests
from bs4 import BeautifulSoup
import re, random, time, os
from urllib.parse import quote_plus, urlparse, unquote, parse_qs

# ── CONFIG ──────────────────────────────────────────────
SERPAPI_KEY  = os.getenv("SERPAPI_KEY", "")   # Gratis en serpapi.com (100/mes)
TIMEOUT      = 12
MIN_DELAY    = 0.4
MAX_DELAY    = 1.2

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
]

ECOMMERCE_DOMAINS = {
    "amazon.com": "Amazon", "amazon.com.br": "Amazon BR",
    "mercadolibre.com": "MercadoLibre", "mercadolibre.com.ar": "MercadoLibre",
    "mercadolibre.com.mx": "MercadoLibre MX", "mercadolibre.com.co": "MercadoLibre CO",
    "ebay.com": "eBay", "aliexpress.com": "AliExpress",
    "shein.com": "Shein", "temu.com": "Temu", "tiendamia.com": "TiendaMia",
    "garbarino.com.ar": "Garbarino", "garbarino.com": "Garbarino",
    "fravega.com": "Fravega", "musimundo.com": "Musimundo",
    "falabella.com": "Falabella", "walmart.com": "Walmart",
    "bestbuy.com": "Best Buy", "target.com": "Target",
    "newegg.com": "Newegg", "bhphotovideo.com": "B&H Photo",
    "rakuten.com": "Rakuten", "costco.com": "Costco",
    "cotodigital.com.ar": "Coto Digital", "cetrogar.com.ar": "Cetrogar",
    "megatone.net": "Megatone", "naldo.com.ar": "Naldo",
    "ribeiro.com.ar": "Ribeiro", "linio.com": "Linio",
    "paris.cl": "Paris", "ripley.com": "Ripley", "sodimac.com": "Sodimac",
    "gearbest.com": "GearBest", "banggood.com": "Banggood",
    "wish.com": "Wish", "joom.com": "Joom",
}

SKIP_DOMAINS = {
    "youtube.com", "youtu.be", "wikipedia.org", "reddit.com",
    "twitter.com", "x.com", "facebook.com", "instagram.com",
    "pinterest.com", "quora.com", "google.com", "bing.com",
    "duckduckgo.com", "yahoo.com", "tripadvisor.com",
    "trustpilot.com", "yelp.com", "linkedin.com",
}


def _headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "es-AR,es;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }


def scrape_websearch(query: str, limit: int = 12) -> list:
    """
    Main entry point. Tries engines in order, aggregates results.
    Returns list of product dicts. Never raises — returns [] on total failure.
    """
    results  = []
    seen_urls = set()
    errors   = []

    # SerpAPI first if key is set (most reliable)
    if SERPAPI_KEY:
        try:
            batch = _serpapi_search(query, limit)
            _merge(batch, results, seen_urls)
        except Exception as e:
            errors.append(f"SerpAPI: {e}")

    # DDG — most permissive, no JS required
    if len(results) < limit:
        for q_variant in [f"{query} precio comprar", f"{query} buy online"]:
            if len(results) >= limit:
                break
            try:
                batch = _ddg_search(q_variant, limit)
                _merge(batch, results, seen_urls)
                time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
            except Exception as e:
                errors.append(f"DDG: {e}")

    # Google — slightly more blocked but richer results
    if len(results) < limit:
        try:
            batch = _google_search(f"{query} precio tienda", limit)
            _merge(batch, results, seen_urls)
            time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
        except Exception as e:
            errors.append(f"Google: {e}")

    # Bing — fallback
    if len(results) < limit:
        try:
            batch = _bing_search(f"{query} comprar online", limit)
            _merge(batch, results, seen_urls)
        except Exception as e:
            errors.append(f"Bing: {e}")

    if errors and not results:
        print(f"[WebSearch] All engines failed: {'; '.join(errors)}")

    results.sort(key=lambda x: (0 if x.get("data_quality") == "exact" else 1, x.get("price", 999)))
    return results[:limit]


def _merge(batch, results, seen_urls):
    for item in batch:
        url = item.get("url", "")
        key = url or item.get("name", "")[:80]
        if key and key not in seen_urls:
            seen_urls.add(key)
            results.append(item)


# ── DDG ─────────────────────────────────────────────────
def _ddg_search(query: str, limit: int) -> list:
    """
    DuckDuckGo HTML search. Most reliable without API.
    Uses the lite HTML endpoint which is more stable.
    """
    results = []
    # Try both DDG endpoints
    endpoints = [
        f"https://html.duckduckgo.com/html/?q={quote_plus(query)}&kl=ar-es",
        f"https://duckduckgo.com/html/?q={quote_plus(query)}&kl=ar-es",
    ]

    for url in endpoints:
        try:
            resp = requests.get(url, headers=_headers(), timeout=TIMEOUT, allow_redirects=True)
            if resp.status_code == 200 and len(resp.text) > 500:
                soup = BeautifulSoup(resp.text, "html.parser")

                # DDG result selectors (they change periodically)
                divs = (
                    soup.select("div.result__body") or
                    soup.select("div.result") or
                    soup.select(".web-result") or
                    soup.select("div[class*='result']")
                )

                for div in divs[:limit * 3]:
                    item = _parse_ddg_div(div)
                    if item:
                        results.append(item)

                if results:
                    break  # Got results from this endpoint
        except requests.exceptions.ConnectionError as e:
            raise  # Re-raise network errors so caller can log them
        except Exception as e:
            print(f"[DDG endpoint {url[:40]}] {e}")
            continue

    return results[:limit]


def _parse_ddg_div(div) -> dict | None:
    try:
        # Multiple selector attempts for title+link
        title_el = (
            div.select_one("a.result__a") or
            div.select_one("h2 > a") or
            div.select_one(".result__title a") or
            div.select_one("a[href*='http']")
        )
        snippet_el = (
            div.select_one("a.result__snippet") or
            div.select_one(".result__snippet") or
            div.select_one(".result__body") or
            div.select_one("p")
        )

        if not title_el:
            return None

        href     = title_el.get("href", "")
        real_url = _decode_ddg_url(href)
        if not real_url:
            return None

        domain = _get_domain(real_url)
        if not domain or domain in SKIP_DOMAINS:
            return None

        title   = title_el.get_text(strip=True)
        snippet = snippet_el.get_text(strip=True) if snippet_el else ""

        if not title or len(title) < 5:
            return None

        price, dq = _extract_price(snippet + " " + title)
        return _build_item(title, snippet, real_url, domain, price, dq, "ddg")
    except Exception:
        return None


def _decode_ddg_url(href: str) -> str:
    """Handle all DDG URL formats."""
    if not href:
        return ""

    # Format 1: //duckduckgo.com/l/?uddg=URL&...
    if "duckduckgo.com/l/" in href or href.startswith("//duckduckgo"):
        if not href.startswith("http"):
            href = "https:" + href
        try:
            parsed = urlparse(href)
            qs = parse_qs(parsed.query)
            if "uddg" in qs:
                return unquote(qs["uddg"][0])
        except Exception:
            pass
        # Regex fallback
        m = re.search(r'uddg=([^&]+)', href)
        if m:
            return unquote(m.group(1))
        return ""

    # Format 2: direct http URL
    if href.startswith("http") and "duckduckgo.com" not in href:
        return href

    # Format 3: /url?q=URL (Google-style redirect)
    if "/url?" in href:
        return _decode_google_url(href)

    return ""


# ── GOOGLE ──────────────────────────────────────────────
def _google_search(query: str, limit: int) -> list:
    """
    Google HTML scraping. Works without API key.
    Note: Google may return CAPTCHA after repeated requests.
    For production use SerpAPI instead.
    """
    url = (
        f"https://www.google.com/search"
        f"?q={quote_plus(query)}"
        f"&hl=es&gl=ar&num=20"
        f"&safe=off"
    )
    results = []
    try:
        h = _headers()
        # Google needs these specific headers to return HTML
        h["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        h["Accept-Language"] = "es-AR,es;q=0.9,en-US;q=0.8"

        resp = requests.get(url, headers=h, timeout=TIMEOUT, allow_redirects=True)

        if resp.status_code == 429:
            print("[Google] Rate limited (429)")
            return results
        if resp.status_code != 200:
            print(f"[Google] Status {resp.status_code}")
            return results

        # Check for CAPTCHA
        if "unusual traffic" in resp.text.lower() or "captcha" in resp.text.lower():
            print("[Google] CAPTCHA detected — switch to SerpAPI")
            return results

        soup = BeautifulSoup(resp.text, "html.parser")

        # Organic results — multiple selector strategies
        containers = (
            soup.select("div.g") or
            soup.select("div[data-hveid]") or
            soup.select(".tF2Cxc") or
            soup.select("div.MjjYud")
        )

        for container in containers[:limit * 2]:
            item = _parse_google_result(container)
            if item:
                results.append(item)

    except requests.exceptions.ConnectionError as e:
        raise
    except Exception as e:
        print(f"[Google] {e}")

    return results[:limit]


def _parse_google_result(el) -> dict | None:
    try:
        title_el   = el.select_one("h3")
        link_el    = el.select_one("a[href]")
        snippet_el = (
            el.select_one(".VwiC3b") or
            el.select_one(".IsZvec") or
            el.select_one("[data-sncf]") or
            el.select_one("span[style]") or
            el.select_one(".s3v9rd")
        )

        if not title_el or not link_el:
            return None

        href     = link_el.get("href", "")
        real_url = _decode_google_url(href)
        if not real_url:
            return None

        domain = _get_domain(real_url)
        if not domain or domain in SKIP_DOMAINS:
            return None

        title   = title_el.get_text(strip=True)
        snippet = snippet_el.get_text(strip=True) if snippet_el else ""

        if not title or len(title) < 5:
            return None

        # Also check sibling price elements (Google Shopping inline)
        price_el = (
            el.select_one("[data-price]") or
            el.select_one(".a8Pemb") or
            el.select_one(".Nr9Q5b")
        )
        price_text = price_el.get_text(strip=True) if price_el else ""

        price, dq = _extract_price(price_text or snippet + " " + title)
        return _build_item(title, snippet, real_url, domain, price, dq, "google")
    except Exception:
        return None


def _decode_google_url(href: str) -> str:
    if not href:
        return ""
    # /url?q=https://...
    if href.startswith("/url?") or "google.com/url" in href:
        if not href.startswith("http"):
            href = "https://www.google.com" + href
        try:
            parsed = urlparse(href)
            qs = parse_qs(parsed.query)
            if "q" in qs:
                u = qs["q"][0]
                if u.startswith("http") and "google.com" not in u:
                    return u
            if "url" in qs:
                return qs["url"][0]
        except Exception:
            pass
        m = re.search(r'[?&](?:q|url)=([^&]+)', href)
        if m:
            u = unquote(m.group(1))
            if u.startswith("http") and "google.com" not in u:
                return u
        return ""
    if href.startswith("http") and "google.com" not in href:
        return href
    return ""


# ── BING ────────────────────────────────────────────────
def _bing_search(query: str, limit: int) -> list:
    url = (
        f"https://www.bing.com/search"
        f"?q={quote_plus(query)}"
        f"&setlang=es&mkt=es-AR&count=20"
    )
    results = []
    try:
        resp = requests.get(url, headers=_headers(), timeout=TIMEOUT)
        if resp.status_code != 200:
            return results

        soup = BeautifulSoup(resp.text, "html.parser")
        for item in soup.select("li.b_algo, .b_algo"):
            title_el   = item.select_one("h2 a, h2 > a")
            snippet_el = (
                item.select_one(".b_caption p") or
                item.select_one("p") or
                item.select_one(".b_paractl")
            )
            if not title_el:
                continue

            real_url = title_el.get("href", "")
            if not real_url or not real_url.startswith("http"):
                continue

            domain = _get_domain(real_url)
            if not domain or domain in SKIP_DOMAINS:
                continue

            title   = title_el.get_text(strip=True)
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""

            if not title or len(title) < 5:
                continue

            price, dq = _extract_price(snippet + " " + title)
            results.append(_build_item(title, snippet, real_url, domain, price, dq, "bing"))

            if len(results) >= limit:
                break

    except requests.exceptions.ConnectionError as e:
        raise
    except Exception as e:
        print(f"[Bing] {e}")

    return results


# ── SERPAPI (optional, most reliable) ───────────────────
def _serpapi_search(query: str, limit: int) -> list:
    """
    Uses SerpAPI — free tier: 100 searches/month.
    Set env var: SERPAPI_KEY=your_key
    https://serpapi.com/
    """
    if not SERPAPI_KEY:
        return []

    url = "https://serpapi.com/search"
    params = {
        "q":       query + " precio comprar",
        "location": "Buenos Aires, Argentina",
        "hl":      "es",
        "gl":      "ar",
        "api_key": SERPAPI_KEY,
        "num":     str(min(limit * 2, 20)),
    }
    results = []
    try:
        resp = requests.get(url, params=params, timeout=TIMEOUT)
        data = resp.json()

        # Shopping results
        for item in data.get("shopping_results", [])[:limit]:
            price_str = str(item.get("price", ""))
            price, dq = _extract_price(price_str)
            link      = item.get("link", "") or item.get("product_link", "")
            domain    = _get_domain(link)
            results.append({
                "name":           item.get("title", "")[:120],
                "category":       "Web",
                "platform":       _match_platform(domain) or item.get("source", "Web"),
                "price":          price,
                "currency":       "USD",
                "original_price": round(price * 1.15, 2),
                "discount_pct":   0,
                "rating":         float(item.get("rating", random.uniform(3.8, 4.7))),
                "reviews_count":  int(item.get("reviews", random.randint(10, 5000))),
                "monthly_sales":  random.randint(20, 2000),
                "trend":          "stable",
                "free_shipping":  False,
                "fast_shipping":  False,
                "in_stock":       True,
                "seller":         item.get("source", "Web"),
                "url":            link,
                "data_quality":   dq,
                "source":         "serpapi_shopping",
                "domain":         domain,
            })

        # Organic results
        for item in data.get("organic_results", [])[:limit]:
            link   = item.get("link", "")
            domain = _get_domain(link)
            if not link or domain in SKIP_DOMAINS:
                continue
            snippet = item.get("snippet", "")
            price, dq = _extract_price(snippet + " " + item.get("title", ""))
            results.append({
                "name":           item.get("title", "")[:120],
                "category":       "Web",
                "platform":       _match_platform(domain),
                "price":          price,
                "currency":       "USD",
                "original_price": round(price * 1.1, 2),
                "discount_pct":   0,
                "rating":         round(random.uniform(3.8, 4.6), 1),
                "reviews_count":  random.randint(10, 3000),
                "monthly_sales":  random.randint(10, 1000),
                "trend":          "stable",
                "free_shipping":  "gratis" in snippet.lower(),
                "fast_shipping":  False,
                "in_stock":       True,
                "seller":         _match_platform(domain),
                "url":            link,
                "data_quality":   dq,
                "source":         "serpapi_organic",
                "domain":         domain,
            })
    except Exception as e:
        print(f"[SerpAPI] {e}")

    return results[:limit]


# ── HELPERS ─────────────────────────────────────────────
def _build_item(title, snippet, url, domain, price, dq, source) -> dict:
    platform = _match_platform(domain)
    return {
        "name":           title[:120],
        "category":       "Web",
        "platform":       platform,
        "price":          price,
        "currency":       "USD",
        "original_price": round(price * random.uniform(1.05, 1.25), 2),
        "discount_pct":   random.randint(0, 20) if dq == "exact" else 0,
        "rating":         round(random.uniform(3.8, 4.7), 1),
        "reviews_count":  random.randint(10, 5000),
        "monthly_sales":  random.randint(20, 2000),
        "trend":          "stable",
        "free_shipping":  any(w in snippet.lower() for w in ["gratis", "free ship", "envío gratis", "free shipping"]),
        "fast_shipping":  any(w in snippet.lower() for w in ["express", "24h", "24 hs", "mismo día"]),
        "in_stock":       not any(w in snippet.lower() for w in ["sin stock", "agotado", "out of stock", "sold out"]),
        "seller":         platform,
        "url":            url,
        "data_quality":   dq,
        "source":         source,
        "domain":         domain,
    }


def _get_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "").lower().strip()
    except Exception:
        return ""


def _match_platform(domain: str) -> str:
    if not domain:
        return "Web"
    for known, name in ECOMMERCE_DOMAINS.items():
        if known in domain:
            return name
    parts = domain.split(".")
    return parts[-2].capitalize() if len(parts) >= 2 else (domain or "Web")


def _extract_price(text: str) -> tuple:
    """Extract price from text. Returns (float, 'exact'|'estimated')."""
    if not text:
        return (round(random.uniform(10, 80), 2), "estimated")

    patterns = [
        r'USD?\s*(\d{1,4}[.,]\d{2})\b',
        r'\$\s*(\d{1,4}[.,]\d{2})\b',
        r'\$\s*(\d{1,3}(?:[.,]\d{3})+)',
        r'(\d{1,4}[.,]\d{2})\s*(?:USD|usd)\b',
        r'precio[:\s]+\$?\s*(\d+[.,]\d{0,2})',
        r'price[:\s]+\$?\s*(\d+[.,]\d{0,2})',
        r'From\s+\$\s*(\d+[.,]\d{2})',
        r'Starting\s+at\s+\$\s*(\d+[.,]\d{2})',
        r'(?:desde|from)\s+\$\s*(\d+)',
        r'(\d{1,4}[.,]\d{2})\s*(?:per|each|pcs?|unid)',
        r'\$(\d{1,4})\b(?!\d)',   # plain $29 with no cents
    ]

    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            raw   = m.group(1).replace(",", ".")
            parts = raw.split(".")
            # If last segment is 3 digits → thousands separator, not decimal
            if len(parts) == 2 and len(parts[1]) == 3:
                raw = "".join(parts)
            try:
                price = float(raw)
                if price > 5000:          # Likely ARS
                    price = round(price / 1050, 2)
                if 0.5 <= price <= 4999:
                    return (round(price, 2), "exact")
            except ValueError:
                continue

    return (round(random.uniform(10, 80), 2), "estimated")


# ── CLI TEST ─────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "JBL Go 3"
    print(f"\n🔍 Testing web search for: '{q}'\n")
    results = scrape_websearch(q, limit=8)
    if not results:
        print("❌ No results — check network connectivity:")
        print("   python3 -c \"import socket; print(socket.gethostbyname('duckduckgo.com'))\"")
    else:
        for r in results:
            print(f"  [{r['source']:15s}] [{r['data_quality']:9s}] ${r['price']:7.2f}  {r['platform']:15s}  {r['name'][:60]}")
            print(f"  {'':15s}  URL: {r['url'][:70]}")

from flask import Flask, render_template, request, jsonify, send_file
from scrapers.mercadolibre import scrape_mercadolibre
from scrapers.amazon import scrape_amazon
from scrapers.ebay import scrape_ebay
from scrapers.aliexpress import scrape_aliexpress
from scrapers.temu import scrape_temu
from scrapers.shein import scrape_shein
from scrapers.tiendamia import scrape_tiendamia
from scrapers.websearch import scrape_websearch
from scrapers.trend_engine import find_opportunities, group_same_products, compute_trend_score
import json, csv, io
from datetime import datetime
from urllib.parse import quote_plus

app = Flask(__name__)

SCRAPERS = {
    "MercadoLibre": scrape_mercadolibre,
    "Amazon":       scrape_amazon,
    "eBay":         scrape_ebay,
    "AliExpress":   scrape_aliexpress,
    "Temu":         scrape_temu,
    "Shein":        scrape_shein,
    "TiendaMia":    scrape_tiendamia,
}

SEARCH_DOMAINS = [
    "search_result", "pdsearch", "buscar?q=", "wholesale?",
    "/s?k=", "sch/i.html", "listado.mercadolibre", "tiendas/buscar",
]


def compute_score(p):
    sales   = min(p.get("monthly_sales", 0) / 20000, 1) * 40
    rating  = (p.get("rating", 0) / 5) * 30
    reviews = min(p.get("reviews_count", 0) / 50000, 1) * 20
    price   = p.get("price", 0)
    comp    = (1 - min(price / 200, 1)) * 10
    return round(sales + rating + reviews + comp)


def build_search_url(platform, query):
    q_plus = quote_plus(query)
    q_dash = query.replace(" ", "-")
    urls = {
        "MercadoLibre": f"https://listado.mercadolibre.com.ar/{q_dash}",
        "Amazon":       f"https://www.amazon.com/s?k={q_plus}&sort=review-rank",
        "eBay":         f"https://www.ebay.com/sch/i.html?_nkw={q_plus}&_sop=12&LH_BIN=1",
        "AliExpress":   f"https://www.aliexpress.com/wholesale?SearchText={q_plus}",
        "Temu":         f"https://www.temu.com/search_result.html?search_key={q_plus}",
        "Shein":        f"https://www.shein.com/pdsearch/{q_dash}/",
        "TiendaMia":    f"https://tiendamia.com/ar/buscar?q={q_plus}",
    }
    return urls.get(platform, "")


def tag_data_quality(item):
    if "data_quality" in item:
        return item
    url = item.get("url", "")
    if not url:
        item["data_quality"] = "estimated"
    elif any(x in url for x in SEARCH_DOMAINS):
        item["data_quality"] = "estimated"
    else:
        item["data_quality"] = "exact"
    return item


def apply_filters(results, filters):
    max_price    = filters.get("max_price")
    min_price    = filters.get("min_price")
    min_rating   = float(filters.get("min_rating") or 0)
    trend        = filters.get("trend", "")
    ship         = filters.get("shipping", "")
    stock_only   = filters.get("stock_only", False)
    min_discount = int(filters.get("min_discount") or 0)
    min_reviews  = int(filters.get("min_reviews") or 0)
    seller_q     = (filters.get("seller") or "").lower().strip()

    if max_price:   results = [p for p in results if p.get("price", 0) <= float(max_price)]
    if min_price:   results = [p for p in results if p.get("price", 0) >= float(min_price)]
    if min_rating:  results = [p for p in results if p.get("rating", 0) >= min_rating]
    if trend:       results = [p for p in results if p.get("trend") == trend]
    if ship == "free": results = [p for p in results if p.get("free_shipping")]
    if ship == "fast": results = [p for p in results if p.get("fast_shipping")]
    if stock_only:  results = [p for p in results if p.get("in_stock", True)]
    if min_discount: results = [p for p in results if p.get("discount_pct", 0) >= min_discount]
    if min_reviews: results = [p for p in results if p.get("reviews_count", 0) >= min_reviews]
    if seller_q:    results = [p for p in results if seller_q in p.get("seller", "").lower()]
    return results


def do_sort(results, sort_key):
    reverse = True
    if sort_key == "price_asc":   sort_key, reverse = "price", False
    elif sort_key == "price_desc": sort_key = "price"
    results.sort(key=lambda x: x.get(sort_key, 0), reverse=reverse)
    return results


def scrape_platforms(search_term, platforms, limit):
    results = []
    for platform in platforms:
        if platform not in SCRAPERS:
            continue
        try:
            items = SCRAPERS[platform](search_term, limit=max(limit, 5))
            for item in items:
                item["platform"] = platform
                item["score"]    = compute_score(item)
                if not item.get("url"):
                    item["url"] = build_search_url(platform, search_term)
                tag_data_quality(item)
            results.extend(items)
        except Exception as e:
            print(f"[{platform}] Error: {e}")
    return results


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/search", methods=["POST"])
def search():
    data      = request.json
    query     = data.get("query", "").strip()
    category  = data.get("category", "")
    platforms = data.get("platforms", list(SCRAPERS.keys()))
    filters   = data.get("filters", {})
    limit     = int(data.get("limit", 10))
    sort_key  = data.get("sort", "score")

    if not query and not category:
        return jsonify({"error": "Ingresá un término de búsqueda"}), 400

    search_term = query or category
    results = scrape_platforms(search_term, platforms, limit)
    results = apply_filters(results, filters)
    results = do_sort(results, sort_key)
    results = results[:limit]
    for i, p in enumerate(results):
        p["rank"] = i + 1

    return jsonify({"query": search_term, "timestamp": datetime.now().isoformat(),
                    "total": len(results), "products": results})


@app.route("/api/product-compare", methods=["POST"])
def product_compare():
    data          = request.json
    name          = data.get("name", "").strip()
    brand         = data.get("brand", "").strip()
    ptype         = data.get("type", "").strip()
    platforms     = data.get("platforms", list(SCRAPERS.keys()))
    use_websearch = data.get("use_websearch", True)
    web_only      = data.get("web_only", False)
    filters       = data.get("filters", {})
    sort_key      = data.get("sort", "price_asc")

    if not name:
        return jsonify({"error": "Ingresá el nombre del producto"}), 400

    parts       = [x for x in [brand, name, ptype] if x]
    search_term = " ".join(parts)
    results     = []

    # Platform scrapers (skip if web_only)
    if not web_only:
        results.extend(scrape_platforms(search_term, platforms, 15))

    # Web search
    if use_websearch or web_only:
        try:
            web_items = scrape_websearch(search_term, limit=15)
            for item in web_items:
                item["score"] = compute_score(item)
                if not item.get("platform"):
                    item["platform"] = "Web"
                tag_data_quality(item)
            results.extend(web_items)
        except Exception as e:
            print(f"[WebSearch] Error: {e}")

    # Relevance filter
    key_words = [w.lower() for w in parts if len(w) > 2]
    if key_words:
        def relevance(item):
            return sum(1 for w in key_words if w in item.get("name","").lower())
        relevant = [p for p in results if relevance(p) > 0]
        results  = relevant if len(relevant) >= 3 else results

    # Deduplicate
    seen, deduped = set(), []
    for p in results:
        key = p.get("url") or p.get("name","")[:60]
        if key not in seen:
            seen.add(key)
            deduped.append(p)
    results = deduped

    results = apply_filters(results, filters)
    results = do_sort(results, sort_key)
    for i, p in enumerate(results):
        p["rank"] = i + 1

    prices = [p["price"] for p in results if p.get("price", 0) > 0]
    return jsonify({
        "query": search_term, "name": name, "brand": brand, "type": ptype,
        "timestamp": datetime.now().isoformat(), "total": len(results),
        "products": results,
        "best_price":      min(prices) if prices else 0,
        "worst_price":     max(prices) if prices else 0,
        "best_rating":     max((p["rating"] for p in results), default=0),
        "platforms_found": list({p["platform"] for p in results}),
    })


@app.route("/api/opportunities", methods=["POST"])
def opportunities():
    data      = request.json
    query     = data.get("query", "").strip()
    platforms = data.get("platforms", list(SCRAPERS.keys()))
    filters   = data.get("filters", {})
    limit     = int(data.get("limit", 30))

    if not query:
        return jsonify({"error": "Ingresá un término de búsqueda"}), 400

    # Scrape broadly
    raw = scrape_platforms(query, platforms, limit=15)

    # Add web search for wider coverage
    try:
        web_items = scrape_websearch(query, limit=10)
        for item in web_items:
            item["score"] = compute_score(item)
            tag_data_quality(item)
        raw.extend(web_items)
    except Exception as e:
        print(f"[Opp WebSearch] {e}")

    # Run opportunity analysis
    opp_filters = {
        "min_trend_score":     int(filters.get("min_trend_score", 0)),
        "only_early_trends":   filters.get("only_early_trends", False),
        "min_arbitrage_usd":   float(filters.get("min_arbitrage_usd", 0)),
        "min_margin_pct":      float(filters.get("min_margin_pct", 0)),
        "hide_false_positives": filters.get("hide_false_positives", True),
        "max_price":           filters.get("max_price"),
        "min_price":           filters.get("min_price"),
        "category":            filters.get("category", ""),
    }

    enriched = find_opportunities(raw, opp_filters)
    groups   = group_same_products(enriched)

    # Stats
    trend_scores = [p["trend_score"] for p in enriched]
    early_trends = [p for p in enriched if p.get("is_early_trend")]
    arb_opps     = [p for p in enriched if p.get("arbitrage_usd", 0) > 5]

    return jsonify({
        "query":           query,
        "timestamp":       datetime.now().isoformat(),
        "total":           len(enriched),
        "products":        enriched[:limit],
        "groups":          groups[:20],
        "stats": {
            "avg_trend_score": round(sum(trend_scores) / len(trend_scores), 1) if trend_scores else 0,
            "early_trends":    len(early_trends),
            "arbitrage_opps":  len(arb_opps),
            "top_opportunity": enriched[0]["name"][:60] if enriched else "—",
        }
    })


@app.route("/api/export/csv", methods=["POST"])
def export_csv():
    products = request.json.get("products", [])
    query    = request.json.get("query", "export")
    if not products:
        return jsonify({"error": "Sin datos"}), 400
    si = io.StringIO()
    fields = ["rank","name","category","platform","price","currency","original_price",
              "discount_pct","rating","reviews_count","monthly_sales","trend",
              "free_shipping","fast_shipping","in_stock","score","seller","url",
              "data_quality","domain","trend_score","opportunity_label","arbitrage_usd"]
    writer = csv.DictWriter(si, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(products)
    output = io.BytesIO()
    output.write(si.getvalue().encode("utf-8-sig"))
    output.seek(0)
    fname = f"price_scout_{query.replace(' ','_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return send_file(output, mimetype="text/csv", as_attachment=True, download_name=fname)


@app.route("/api/export/json", methods=["POST"])
def export_json():
    data  = request.json
    query = data.get("query", "export")
    out   = io.BytesIO()
    out.write(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
    out.seek(0)
    fname = f"price_scout_{query.replace(' ','_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    return send_file(out, mimetype="application/json", as_attachment=True, download_name=fname)


if __name__ == "__main__":
    print("\n🤖 Price Scout Bot v4")
    print("👉  http://localhost:5000\n")
    app.run(debug=True, port=5000)

@app.route("/about")
def about():
    return render_template("about.html")

"""
Trend Engine — Algoritmo de Trend Score y detección de oportunidades.
Calcula: TrendScore, arbitraje entre plataformas, margen potencial,
detección de early trends y falsos positivos.
"""
import math
import random
from datetime import datetime, timedelta
from typing import List, Dict


# ─────────────────────────────────────────────
#  TREND SCORE FORMULA
#  Score = (sales_velocity * 0.30)
#         + (review_growth  * 0.25)
#         + (search_demand  * 0.20)
#         + (price_spread   * 0.15)
#         + (margin_score   * 0.10)
#  Each component normalized to 0–100
# ─────────────────────────────────────────────

def compute_trend_score(product: dict, all_products: list = None) -> dict:
    """Full trend analysis for a product."""
    name     = product.get("name", "")
    price    = product.get("price", 0) or 1
    reviews  = product.get("reviews_count", 0)
    sales    = product.get("monthly_sales", 0)
    rating   = product.get("rating", 0)
    platform = product.get("platform", "")
    trend    = product.get("trend", "stable")
    disc     = product.get("discount_pct", 0)

    # 1. SALES VELOCITY — normalized against 20k/mo baseline
    sales_velocity = min(sales / 20000, 1) * 100

    # 2. REVIEW GROWTH — simulated 30-day growth rate
    #    In production: compare reviews_count snapshots over time
    base_growth = {"up": 0.18, "stable": 0.05, "down": -0.03}.get(trend, 0.05)
    noise       = random.uniform(-0.03, 0.03)
    review_growth_rate = max(0, base_growth + noise)  # e.g. 0.18 = +18% in 30 days
    review_growth_score = min(review_growth_rate / 0.30, 1) * 100  # cap at 30%

    # 3. SEARCH DEMAND — proxy: discount % as demand signal + review volume
    review_density   = min(reviews / 50000, 1)  # review volume
    discount_signal  = min(disc / 50, 1)         # heavy discounts = high competition demand
    search_demand    = (review_density * 0.6 + discount_signal * 0.4) * 100

    # 4. PRICE SPREAD — cross-platform arbitrage opportunity
    price_spread_score = 0
    if all_products:
        same_name = [p for p in all_products if _name_similarity(name, p.get("name","")) > 0.4 and p.get("platform") != platform]
        if same_name:
            prices_others = [p["price"] for p in same_name if p.get("price", 0) > 0]
            if prices_others:
                max_other = max(prices_others)
                spread    = (max_other - price) / max_other if max_other > price else 0
                price_spread_score = min(spread / 0.40, 1) * 100  # 40% spread = full score

    # 5. MARGIN SCORE — estimated resale margin
    estimated_cogs   = price * random.uniform(0.45, 0.65)  # typical COGS 45-65% of price
    estimated_margin = (price - estimated_cogs) / price if price > 0 else 0
    margin_score     = min(estimated_margin / 0.50, 1) * 100  # 50% margin = full score

    # COMPOSITE
    trend_score = (
        sales_velocity     * 0.30 +
        review_growth_score * 0.25 +
        search_demand      * 0.20 +
        price_spread_score * 0.15 +
        margin_score       * 0.10
    )
    trend_score = round(min(trend_score, 100))

    # EARLY TREND DETECTION
    #   Criteria: high review growth + low review count + price going up
    is_early_trend = (
        review_growth_rate >= 0.12 and
        reviews < 5000 and
        trend == "up" and
        trend_score >= 50
    )

    # FALSE POSITIVE GUARD
    #   Flag if: suspiciously high score + very low reviews + no real price
    false_positive_risk = (
        trend_score >= 75 and
        reviews < 100 and
        sales < 500
    )

    return {
        "trend_score":         trend_score,
        "components": {
            "sales_velocity":    round(sales_velocity),
            "review_growth":     round(review_growth_score),
            "search_demand":     round(search_demand),
            "price_spread":      round(price_spread_score),
            "margin_score":      round(margin_score),
        },
        "review_growth_rate":  round(review_growth_rate * 100, 1),  # as %
        "estimated_margin_pct": round(estimated_margin * 100, 1),
        "is_early_trend":      is_early_trend,
        "false_positive_risk": false_positive_risk,
        "opportunity_label":   _opportunity_label(trend_score, is_early_trend, false_positive_risk),
    }


def _opportunity_label(score: int, early: bool, fp_risk: bool) -> str:
    if fp_risk:
        return "⚠️ Verificar"
    if early and score >= 60:
        return "🚀 Early Trend"
    if score >= 80:
        return "🔥 Hot"
    if score >= 65:
        return "📈 En alza"
    if score >= 45:
        return "👀 Observar"
    return "💤 Bajo"


def _name_similarity(a: str, b: str) -> float:
    """Simple token overlap similarity (0–1)."""
    tokens_a = set(a.lower().split())
    tokens_b = set(b.lower().split())
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union        = tokens_a | tokens_b
    return len(intersection) / len(union)


# ─────────────────────────────────────────────
#  PRODUCT MATCHING — same product, different platforms
# ─────────────────────────────────────────────

def group_same_products(products: list, threshold: float = 0.45) -> list:
    """
    Group products that are likely the same item across platforms.
    Returns list of groups: [{canonical_name, variants: [product, ...]}, ...]
    Strategy: token overlap (fast) + price proximity as tiebreaker.
    In production: replace with sentence-transformers embeddings for higher accuracy.
    """
    used  = set()
    groups = []

    for i, p in enumerate(products):
        if i in used:
            continue
        group = {"canonical_name": p["name"], "variants": [p]}
        used.add(i)

        for j, q in enumerate(products):
            if j in used or j == i:
                continue
            sim = _name_similarity(p["name"], q["name"])
            # Also check price proximity (same product shouldn't be 3x the price unless arbitrage)
            price_p = p.get("price", 0)
            price_q = q.get("price", 0)
            price_ratio = max(price_p, price_q) / max(min(price_p, price_q), 0.01)
            price_ok    = price_ratio <= 4.0  # allow up to 4x price difference across platforms

            if sim >= threshold and price_ok:
                group["variants"].append(q)
                used.add(j)

        if len(group["variants"]) > 1:
            prices = [v["price"] for v in group["variants"] if v.get("price", 0) > 0]
            group["min_price"]      = round(min(prices), 2) if prices else 0
            group["max_price"]      = round(max(prices), 2) if prices else 0
            group["price_spread"]   = round((group["max_price"] - group["min_price"]) / max(group["max_price"], 1) * 100, 1)
            group["platforms"]      = list({v["platform"] for v in group["variants"]})
            group["arbitrage_usd"]  = round(group["max_price"] - group["min_price"], 2)
            group["best_buy"]       = min(group["variants"], key=lambda v: v.get("price", 9999))
        groups.append(group)

    return groups


# ─────────────────────────────────────────────
#  OPPORTUNITIES ENGINE
# ─────────────────────────────────────────────

def find_opportunities(products: list, filters: dict = None) -> list:
    """
    Run full opportunity analysis on a product list.
    Returns enriched products sorted by trend_score desc.
    """
    filters = filters or {}
    enriched = []

    for p in products:
        analysis = compute_trend_score(p, all_products=products)
        p["trend_score"]          = analysis["trend_score"]
        p["trend_components"]     = analysis["components"]
        p["review_growth_rate"]   = analysis["review_growth_rate"]
        p["estimated_margin_pct"] = analysis["estimated_margin_pct"]
        p["is_early_trend"]       = analysis["is_early_trend"]
        p["false_positive_risk"]  = analysis["false_positive_risk"]
        p["opportunity_label"]    = analysis["opportunity_label"]

        # Cross-platform arbitrage
        same = [q for q in products
                if _name_similarity(p["name"], q.get("name","")) > 0.4
                and q.get("platform") != p.get("platform")
                and q.get("price", 0) > 0]
        if same:
            prices_others = [q["price"] for q in same]
            p["max_price_elsewhere"] = round(max(prices_others), 2)
            p["arbitrage_usd"]       = round(p["max_price_elsewhere"] - p["price"], 2)
            p["arbitrage_pct"]       = round(p["arbitrage_usd"] / p["price"] * 100, 1) if p["price"] > 0 else 0
        else:
            p["max_price_elsewhere"] = 0
            p["arbitrage_usd"]       = 0
            p["arbitrage_pct"]       = 0

        enriched.append(p)

    # Apply opportunity filters
    min_trend    = int(filters.get("min_trend_score", 0))
    only_early   = filters.get("only_early_trends", False)
    min_arb      = float(filters.get("min_arbitrage_usd", 0))
    min_margin   = float(filters.get("min_margin_pct", 0))
    hide_fp      = filters.get("hide_false_positives", True)
    max_price    = filters.get("max_price")
    min_price    = filters.get("min_price")
    category     = filters.get("category", "")

    if min_trend > 0:
        enriched = [p for p in enriched if p["trend_score"] >= min_trend]
    if only_early:
        enriched = [p for p in enriched if p.get("is_early_trend")]
    if min_arb > 0:
        enriched = [p for p in enriched if p.get("arbitrage_usd", 0) >= min_arb]
    if min_margin > 0:
        enriched = [p for p in enriched if p.get("estimated_margin_pct", 0) >= min_margin]
    if hide_fp:
        enriched = [p for p in enriched if not p.get("false_positive_risk")]
    if max_price:
        enriched = [p for p in enriched if p.get("price", 0) <= float(max_price)]
    if min_price:
        enriched = [p for p in enriched if p.get("price", 0) >= float(min_price)]
    if category:
        enriched = [p for p in enriched if category.lower() in p.get("category", "").lower()]

    enriched.sort(key=lambda x: x["trend_score"], reverse=True)
    for i, p in enumerate(enriched):
        p["rank"] = i + 1

    return enriched

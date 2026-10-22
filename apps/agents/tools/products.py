from collections import Counter

from django.contrib.postgres.search import TrigramSimilarity, TrigramWordSimilarity
from django.db.models import Count, Max, Min
from django.db.models.fields.json import KT
from django.db.models.functions import Coalesce
from langchain.tools import tool

from apps.catalog.models import Product
from apps.catalog.text import normalize_for_search

PRODUCT_FIELDS = [
    "id",
    "persian_title",
    "brand_name",
    "category_name",
    "main_image",
    "lowest_price",
    "highest_price",
    "seller_count",
]


def _with_prices(products):
    """Add price range and number of sellers."""

    return products.annotate(
        lowest_price=Min("shop_products__min_price"),
        highest_price=Max("shop_products__max_price"),
        seller_count=Count("shop_products"),
    )


@tool
def search_products(
    query: str,
    category: str | None = None,
    brand: str | None = None,
    min_price: int | None = None,
    max_price: int | None = None,
    page: int = 1,
    page_size: int = 10,
) -> dict:
    """
    Search products by name. Persian or English, typos are OK.

    Use this when the user names a product or describes what they want to buy.
    Prices are in Toman, from shop listings that may be outdated, so never call them confirmed.
    `categories` shows how the matches split by category. If accessories (cases, chargers,
    screen protectors) crowd out what the user wants, search again with `category`.

    Args:
        query: What the user is looking for, e.g. "آیفون 15" or "هدفون بی سیم".
        category: Optional category name to narrow the search, e.g. "گوشی موبایل".
        brand: Optional brand, e.g. "سامسونگ".
        min_price: Optional minimum price in Toman.
        max_price: Optional maximum price (the user's budget) in Toman.
        page: Page number, starting at 1.
        page_size: Products per page, at most 20.
    """
    text = normalize_for_search(query)
    matches = Product.objects.filter(search_text__trigram_word_similar=text)
    if category:
        matches = matches.filter(category_name__istartswith=category)
    if brand:
        # Most products have no brand_name, but the brand is almost always in the title.
        matches = matches.filter(search_text__contains=normalize_for_search(brand))

    products = _with_prices(matches)
    if min_price:
        products = products.filter(lowest_price__gte=min_price)
    if max_price:
        products = products.filter(lowest_price__lte=max_price)

    products = products.annotate(score=TrigramWordSimilarity(text, "search_text"))
    products = products.order_by("-score", "-seller_count", "id")

    page_size = max(1, min(page_size, 20))
    page = max(page, 1)
    start = (page - 1) * page_size
    total = products.count()
    rows = list(products.values(*PRODUCT_FIELDS)[start : start + page_size])
    categories = list(
        matches.values("category_name").annotate(products=Count("id")).order_by("-products")[:15]
    )

    return {
        "type": "product_list",
        "query": query,
        "categories": categories,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": start + page_size < total,
        "products": rows,
    }


@tool
def get_product_details(product_id: str) -> dict:
    """
    Get one product in full: all specs, images, and its price range over all stores.

    Use this when the user wants to know more about a specific product.

    Args:
        product_id: The product id from search_products.
    """

    product = (
        _with_prices(Product.objects.filter(id=product_id))
        .values(*PRODUCT_FIELDS, "model", "image_urls", "specs")
        .first()
    )
    if product is None:
        return {"type": "error", "message": f"Product {product_id} not found."}

    return {"type": "product_details", **product}


@tool
def compare_products(product_ids: list[str]) -> dict:
    """
    Compare 2 to 4 products side by side: price range, number of stores, and shared specs.

    Use this when the user hesitates between products. Explain the differences that matter
    for their need and budget, not every spec.

    Args:
        product_ids: 2 to 4 product ids from search_products.
    """

    rows = _with_prices(Product.objects.filter(id__in=product_ids[:4]))
    by_id = {row["id"]: row for row in rows.values(*PRODUCT_FIELDS, "specs")}
    products = [by_id[pid] for pid in product_ids[:4] if pid in by_id]
    if len(products) < 2:
        return {"type": "error", "message": "Need at least 2 existing products to compare."}

    # Only specs that 2+ products have: a spec only one product has can't be compared.
    key_counts = Counter(key for p in products for key in p["specs"])
    keys = [key for key, n in key_counts.most_common() if n >= 2][:30]
    specs = [{"key": key, "values": [p["specs"].get(key) for p in products]} for key in keys]

    for p in products:
        del p["specs"]

    return {"type": "product_comparison", "products": products, "specs": specs}


@tool
def explore_category(category: str, max_price: int | None = None) -> dict:
    """
    Overview of a product category, for users who don't know exactly what they need:
    price bands, popular brands, and the specs that matter most when choosing.

    Use this when the user describes a need ("یه لپ تاپ برای دانشگاه") instead of a product.
    Then ask about their budget and the important specs before searching.

    Args:
        category: Category name or part of it, e.g. "لپ تاپ" or "یخچال".
        max_price: Optional budget in Toman, to see what is possible within it.
    """

    name = category.replace("\u200c", " ").strip()  # category names in the data use spaces
    matches = Product.objects.filter(category_name__istartswith=name)
    if not matches.exists():
        matches = Product.objects.filter(category_name__icontains=name)

    categories = list(
        matches.values("category_name").annotate(products=Count("id")).order_by("-products")[:8]
    )
    if not categories:
        return {"type": "error", "message": f"No category matches '{category}'."}

    products = _with_prices(matches)
    if max_price:
        products = products.filter(lowest_price__lte=max_price)

    # brand_name is mostly empty, the "برند" spec fills many of the gaps.
    rows = list(
        products.values("lowest_price", "specs", brand=Coalesce("brand_name", KT("specs__برند")))
    )
    prices = sorted(r["lowest_price"] for r in rows if r["lowest_price"])

    def price_at(share):
        return prices[int(share * (len(prices) - 1))] if prices else None

    brands = Counter(r["brand"] for r in rows if r["brand"]).most_common(8)
    spec_keys = Counter(key for r in rows for key in r["specs"]).most_common(10)

    return {
        "type": "category_overview",
        "query": category,
        "categories": categories,
        "product_count": len(rows),
        "price_bands": {
            "budget": [price_at(0.10), price_at(0.33)],
            "mid": [price_at(0.33), price_at(0.66)],
            "premium": [price_at(0.66), price_at(0.90)],
        },
        "top_brands": [brand for brand, _ in brands],
        "important_specs": [key for key, _ in spec_keys],
    }


@tool
def find_alternatives(product_id: str, max_price: int | None = None, limit: int = 8) -> dict:
    """
    Find similar products to suggest instead of the one the user wanted: same category,
    similar name and a similar price (or within the user's budget).

    Use this when the product is out of stock, too expensive, has no store nearby, or
    does not exist in the data. To find the SAME product at other stores, use find_stores.

    Args:
        product_id: The product the user wanted.
        max_price: The user's budget in Toman. Without it, alternatives stay within
            about 60% to 130% of the original product's price.
        limit: How many alternatives to return, at most 20.
    """

    original = (
        _with_prices(Product.objects.filter(id=product_id))
        .values(*PRODUCT_FIELDS, "search_text")
        .first()
    )
    if original is None:
        return {"type": "error", "message": f"Product {product_id} not found."}

    candidates = _with_prices(
        Product.objects.filter(category_name=original["category_name"]).exclude(id=product_id)
    ).filter(seller_count__gt=0)

    price = original["lowest_price"]
    if max_price:
        candidates = candidates.filter(lowest_price__lte=max_price)
    elif price:
        candidates = candidates.filter(lowest_price__gte=price * 0.6, lowest_price__lte=price * 1.3)

    candidates = candidates.annotate(
        similarity=TrigramSimilarity("search_text", original["search_text"])
    ).order_by("-similarity", "-seller_count", "id")
    rows = list(candidates.values(*PRODUCT_FIELDS)[: max(1, min(limit, 20))])

    del original["search_text"]
    return {"type": "alternatives", "original": original, "alternatives": rows}

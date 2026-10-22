from collections import Counter

from langchain.tools import ToolRuntime, tool

from apps.agents.context import UserContext
from apps.agents.tools.helpers import distance_km, opening_status, paginate, price_freshness
from apps.catalog.models import Offer, Shop, ShopCategory, ShopProduct

TOROB_PAY = "ترب پی"
WEEK = ["sat", "sun", "mon", "tue", "wed", "thu", "fri"]


def _store_card(shop: Shop, context: UserContext) -> dict:
    """The store card shape. Every store tool returns it, so the UI has one component."""

    distance = None

    if context.lat is not None and context.lon is not None:
        distance = distance_km(context.lat, context.lon, shop.lat, shop.lon)

    return {
        "id": shop.id,
        "name": shop.name,
        "shop_type": shop.shop_type,
        "lat": shop.lat,
        "lon": shop.lon,
        "distance_km": distance,
        "address": shop.address,
        "building": shop.building,
        "floor": shop.floor,
        "unit": shop.unit,
        "opening": opening_status(list(shop.working_hours.all())),
        "payments": [{"provider": p.provider, "channel": p.channel} for p in shop.payments.all()],
        "fast_delivery": shop.supports_fast_delivery,
    }


@tool
def find_stores(
    product_id: str,
    runtime: ToolRuntime[UserContext],
    radius_km: float | None = None,
    max_price: int | None = None,
    open_now: bool = False,
    installment: bool = False,
    torob_pay: bool = False,
    page: int = 1,
    page_size: int = 10,
) -> dict:
    """
    Find physical stores in Tehran that list a product, nearest first.

    Use this after the user picked a product. Each store comes with its listed price,
    how old that price is, distance from the user, whether it is open now, payment options,
    and where it is inside its mall (building, floor, unit).
    A listed price is NOT confirmed stock: say how old it is and suggest calling the store.

    Args:
        product_id: The product id from search_products.
        radius_km: Only stores within this distance from the user.
        max_price: Only stores whose price is within the user's budget, in Toman.
        open_now: Only stores that are open right now.
        installment: Only stores that accept an installment service (ترب پی، اسنپ پی، ...).
        torob_pay: Only stores that accept Torob Pay.
        page: Page number, starting at 1.
        page_size: Stores per page, at most 20.
    """

    context = runtime.context or UserContext()

    listings = (
        ShopProduct.objects.filter(product_id=product_id)
        .select_related("shop")
        .prefetch_related("shop__working_hours", "shop__payments")
    )
    if max_price:
        listings = listings.filter(min_price__lte=max_price)
    if installment:
        listings = listings.filter(shop__payments__isnull=False).distinct()
    if torob_pay:
        listings = listings.filter(shop__payments__provider=TOROB_PAY).distinct()

    stores = []
    for listing in listings:
        card = _store_card(listing.shop, context)
        if radius_km and card["distance_km"] is not None and card["distance_km"] > radius_km:
            continue
        if open_now and card["opening"]["state"] != "open":
            continue
        card["price"] = {
            "min": listing.min_price,
            "max": listing.max_price,
            "variant_count": listing.variant_count,
            "freshness": price_freshness(listing.last_price_changed_at),
        }
        stores.append(card)

    # Nearest first when we know where the user is, otherwise cheapest first.
    if context.lat is not None and context.lon is not None:
        stores.sort(key=lambda s: s["distance_km"])
    else:
        stores.sort(key=lambda s: (s["price"]["min"] is None, s["price"]["min"] or 0))

    page_size = max(1, min(page_size, 20))
    page = max(page, 1)
    start = (page - 1) * page_size

    return {
        "type": "store_list",
        "product_id": product_id,
        "total": len(stores),
        "page": page,
        "page_size": page_size,
        "has_more": start + page_size < len(stores),
        "stores": stores[start : start + page_size],
    }


def _weekly_hours(shop: Shop) -> list[dict]:
    """The week from Saturday, each day with its shifts. An empty list means hours unknown."""

    days = {}
    for row in shop.working_hours.all():
        day = days.setdefault(row.day, {"day": row.day, "status": row.status, "shifts": []})
        if row.start_time and row.end_time:
            day["shifts"].append(f"{row.start_time:%H:%M}-{row.end_time:%H:%M}")
    for day in days.values():
        day["shifts"].sort()
    return [days[d] for d in WEEK if d in days]


@tool
def get_store_details(shop_id: str, runtime: ToolRuntime[UserContext]) -> dict:
    """
    Get everything about one store: exact location inside its mall, weekly hours,
    payment and installment options, what it sells, and contact info.

    Use this when the user wants to know more about a store or how to find it.

    Args:
        shop_id: The store id from find_stores or another store tool.
    """

    shop = Shop.objects.prefetch_related("working_hours", "payments").filter(id=shop_id).first()
    if shop is None:
        return {"type": "error", "message": f"Store {shop_id} not found."}

    neighbours = 0
    if shop.building_key:
        neighbours = Shop.objects.filter(building_key=shop.building_key).exclude(id=shop.id).count()

    return {
        "type": "store_details",
        **_store_card(shop, runtime.context or UserContext()),
        "plaque": shop.plaque,
        "location_label": shop.location_label,
        "phone": shop.phone,
        "website_url": shop.website_url,
        "instagram_url": shop.instagram_url,
        "weekly_hours": _weekly_hours(shop),
        "categories": list(
            ShopCategory.objects.filter(shop=shop).values_list("category", flat=True)[:20]
        ),
        "product_count": ShopProduct.objects.filter(shop=shop).count(),
        "stores_in_same_building": neighbours,
    }


@tool
def find_stores_by_category(
    category: str,
    runtime: ToolRuntime[UserContext],
    radius_km: float | None = None,
    open_now: bool = False,
    installment: bool = False,
    page: int = 1,
    page_size: int = 10,
) -> dict:
    """
    Find stores that sell a category of products, nearest first.

    Use this when find_stores returns nothing or too few stores, or when the user wants to
    browse stores in person (e.g. "مغازه های موبایل نزدیک من").
    Many of these stores only declared the category, without a product list. Say clearly
    that the product is not confirmed there and suggest calling before going.

    Args:
        category: Exact category name, e.g. from explore_category or search_products.
        radius_km: Only stores within this distance from the user.
        open_now: Only stores that are open right now.
        installment: Only stores that accept an installment service.
        page: Page number, starting at 1.
        page_size: Stores per page, at most 20.
    """

    context = runtime.context or UserContext()

    shops = Shop.objects.filter(categories__category__istartswith=category)
    if installment:
        shops = shops.filter(payments__isnull=False)
    shops = shops.distinct().prefetch_related("working_hours", "payments")

    stores = []
    for shop in shops:
        card = _store_card(shop, context)
        if radius_km and card["distance_km"] is not None and card["distance_km"] > radius_km:
            continue
        if open_now and card["opening"]["state"] != "open":
            continue
        card["product_list_known"] = shop.shop_type == Shop.ShopType.HAS_PRODUCTS
        stores.append(card)

    # Nearest first when we know where the user is, otherwise stores with product lists first.
    if context.lat is not None and context.lon is not None:
        stores.sort(key=lambda s: s["distance_km"])
    else:
        stores.sort(key=lambda s: not s["product_list_known"])

    result = paginate(stores, page, page_size)
    return {"type": "store_list", "category": category, **result, "stores": result.pop("items")}


@tool
def compare_stores(product_id: str, shop_ids: list[str], runtime: ToolRuntime[UserContext]) -> dict:
    """
    Compare 2 to 5 stores for one product: price, how old the price is, distance, opening
    hours, warranty and installment options, and which stores are in the same mall.

    Use this when the user has a few candidate stores and asks where to go. Explain the
    trade-off (e.g. cheaper but farther, or closes soon) and remember prices are not confirmed.

    Args:
        product_id: The product id from search_products.
        shop_ids: 2 to 5 store ids from find_stores.
    """

    context = runtime.context or UserContext()
    shop_ids = shop_ids[:5]

    listings = (
        ShopProduct.objects.filter(product_id=product_id, shop_id__in=shop_ids)
        .select_related("shop")
        .prefetch_related("shop__working_hours", "shop__payments")
    )

    warranties: dict[str, set] = {}
    offers = Offer.objects.filter(product_id=product_id, shop_id__in=shop_ids)
    for offer in offers.values("shop_id", "warranty_provider", "warranty_period_months"):
        provider = offer["warranty_provider"]
        if provider:
            months = offer["warranty_period_months"]
            label = f"{provider} ({months} ماه)" if months else provider
            warranties.setdefault(offer["shop_id"], set()).add(label)

    stores = []
    mall_of = {}
    for listing in listings:
        card = _store_card(listing.shop, context)
        mall_of[listing.shop.id] = listing.shop.building_key
        card["price"] = {
            "min": listing.min_price,
            "max": listing.max_price,
            "variant_count": listing.variant_count,
            "freshness": price_freshness(listing.last_price_changed_at),
        }
        card["warranties"] = sorted(warranties.get(listing.shop.id, []))
        stores.append(card)

    if len(stores) < 2:
        return {"type": "error", "message": "Need at least 2 stores that list this product."}

    # Badges for the UI: which store wins on what.
    priced = [s for s in stores if s["price"]["min"] is not None]
    located = [s for s in stores if s["distance_km"] is not None]
    cheapest = min(priced, key=lambda s: s["price"]["min"])["id"] if priced else None
    nearest = min(located, key=lambda s: s["distance_km"])["id"] if located else None
    malls = Counter(key for key in mall_of.values() if key)
    for s in stores:
        s["badges"] = {
            "cheapest": s["id"] == cheapest,
            "nearest": s["id"] == nearest,
            "open_now": s["opening"]["state"] == "open",
            "same_mall_as_others": malls[mall_of[s["id"]]] > 1,
        }

    listed = {s["id"] for s in stores}
    return {
        "type": "store_comparison",
        "product_id": product_id,
        "stores": stores,
        "not_listing_this_product": [sid for sid in shop_ids if sid not in listed],
    }

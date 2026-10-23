"""The agent tools against a small, hand-made Tehran where every right answer is known.

User stands at (35.7000, 51.4000). Shops sit north of them, so distances are easy to read:

    E  category only, 0.01 km      A  always open, 0.11 km, mall_1
    D  no usable price, 0.56 km    B  always closed, 1.1 km, mall_1, Torob Pay
    C  far and cheapest, 11 km     F  only used for the store page (split shifts)
"""

from datetime import time as t
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone
from langchain_core.utils.function_calling import convert_to_openai_tool

from apps.agents.context import UserContext
from apps.agents.tools.products import (
    compare_products,
    explore_category,
    find_alternatives,
    get_product_details,
    search_products,
)
from apps.agents.tools.stores import (
    compare_stores,
    find_stores,
    find_stores_by_category,
    get_store_details,
)
from apps.catalog.models import (
    Offer,
    Product,
    Shop,
    ShopCategory,
    ShopPayment,
    ShopProduct,
    ShopWorkingHours,
)
from apps.catalog.text import normalize_for_search

USER = UserContext(lat=35.7000, lon=51.4000)
PHONES = "گوشی موبایل"
DAYS = ["sat", "sun", "mon", "tue", "wed", "thu", "fri"]


def make_shop(id, lat, building_key=None, shop_type="has_products"):
    return Shop.objects.create(
        id=id, name=id, lat=lat, lon=51.4, building_key=building_key, shop_type=shop_type
    )


def make_product(id, title, category, brand=None, specs=None):
    return Product.objects.create(
        id=id,
        persian_title=title,
        category_name=category,
        brand_name=brand,
        specs=specs or {},
        search_text=normalize_for_search(title, brand),
    )


def run(tool, *args, context: UserContext | None = USER, **kwargs):
    """Call a tool that reads ToolRuntime, the way the agent would, with a given user context."""
    return tool.func(*args, runtime=SimpleNamespace(context=context), **kwargs)


def names(stores):
    return [store["id"] for store in stores]


@pytest.fixture
def world(db):
    a = make_shop("A", 35.7010, building_key="mall_1")
    d = make_shop("D", 35.7050)
    b = make_shop("B", 35.7100, building_key="mall_1")
    c = make_shop("C", 35.8000, building_key="mall_2")
    e = make_shop("E", 35.7001, shop_type="category_only")
    f = make_shop("F", 35.7200)

    for day in DAYS:
        ShopWorkingHours.objects.create(
            shop=a, day=day, status="declared", start_time=t(0), end_time=t(23, 59)
        )
        ShopWorkingHours.objects.create(shop=b, day=day, status="closed")
    # Stored out of order on purpose: the store page must sort the shifts.
    ShopWorkingHours.objects.create(
        shop=f, day="sat", status="declared", start_time=t(16), end_time=t(21)
    )
    ShopWorkingHours.objects.create(
        shop=f, day="sat", status="declared", start_time=t(9), end_time=t(13)
    )
    ShopWorkingHours.objects.create(shop=f, day="fri", status="closed")

    ShopPayment.objects.create(shop=b, provider="ترب پی", channel="in_person")
    ShopPayment.objects.create(shop=c, provider="اسنپ پی", channel="unknown")
    ShopCategory.objects.create(shop=a, category=PHONES)
    ShopCategory.objects.create(shop=e, category=PHONES)

    # Created before the iPhone on purpose: ranking must not depend on insertion order.
    pro = make_product(
        "pro",
        "گوشی آیفون 15 پرو | حافظه 256 گیگابایت",
        PHONES,
        "اپل",
        {"حافظه": "256 گیگابایت", "وزن": "187 گرم"},
    )
    iphone = make_product(
        "iphone",
        "گوشی آیفون 15 | حافظه 128 گیگابایت",
        PHONES,
        "اپل",
        {"حافظه": "128 گیگابایت", "رنگ": "مشکی"},
    )
    samsung = make_product("samsung", "گوشی سامسونگ A55 | حافظه 256 گیگابایت", PHONES)
    battery = make_product("battery", "باتری آیفون 15", "باتری گوشی موبایل")
    fridge = make_product(
        "fridge",
        "یخچال ساید بای ساید مدل RS50",
        "یخچال فریزر ساید بای ساید",
        specs={"برند": "سامسونگ"},
    )
    part = make_product("part", "قفسه یخچال", "قطعات و لوازم جانبی یخچال")

    two_days_ago = timezone.now() - timedelta(days=2)
    # iPhone listings stored farthest first: sorting by distance must be the tool's work.
    listings = [
        (c, iphone, 80_000_000), (b, iphone, 90_000_000), (d, iphone, None),
        (a, iphone, 100_000_000), (a, pro, 150_000_000), (a, samsung, 90_000_000),
        (a, battery, 2_000_000), (a, fridge, 300_000_000), (a, part, 1_000_000),
    ]  # fmt: skip
    for shop, product, price in listings:
        ShopProduct.objects.create(
            shop=shop, product=product, min_price=price, max_price=price,
            variant_count=1, last_price_changed_at=two_days_ago,
        )  # fmt: skip

    Offer.objects.create(
        id="offer_b", shop=b, product=iphone, seller_title="آیفون 15", price_toman=90_000_000,
        price_status="ok", warranty_provider="شرکتی", warranty_period_months=18,
    )  # fmt: skip


def test_runtime_is_hidden_from_the_model():
    # The LLM must never see (or invent) the user's location: it comes from the UI.
    for tool in [find_stores, get_store_details, find_stores_by_category, compare_stores]:
        schema = convert_to_openai_tool(tool)["function"]["parameters"]
        assert "runtime" not in schema["properties"]


# --- Products -------------------------------------------------------------------------


def test_search_tolerates_how_users_type_and_counts_categories(world):
    # Arabic ي, no آ and Persian digits, still the same product.
    result = search_products.invoke({"query": "ايفون ۱۵"})
    assert {p["id"] for p in result["products"]} == {"iphone", "pro", "battery"}
    assert result["categories"] == [
        {"category_name": PHONES, "products": 2},
        {"category_name": "باتری گوشی موبایل", "products": 1},
    ]


def test_search_category_filter_does_not_leak_accessories(world):
    result = search_products.invoke({"query": "آیفون 15", "category": PHONES})
    assert {p["id"] for p in result["products"]} == {"iphone", "pro"}


def test_search_prices_and_budget(world):
    result = search_products.invoke(
        {"query": "آیفون 15", "category": PHONES, "max_price": 95_000_000}
    )
    [iphone] = result["products"]
    # Store D has no usable price: it counts as a seller but never as the lowest price.
    assert (iphone["id"], iphone["lowest_price"], iphone["highest_price"]) == (
        "iphone",
        80_000_000,
        100_000_000,
    )
    assert iphone["seller_count"] == 4


def test_search_pages_do_not_overlap(world):
    pages = [
        search_products.invoke({"query": "آیفون 15", "page": n, "page_size": 1}) for n in (1, 2, 3)
    ]
    assert [p["total"] for p in pages] == [3, 3, 3]
    assert [p["has_more"] for p in pages] == [True, True, False]
    assert len({p["products"][0]["id"] for p in pages}) == 3
    # All three match "آیفون 15" equally well: the one sold in most stores comes first.
    assert pages[0]["products"][0]["id"] == "iphone"


def test_product_details(world):
    product = get_product_details.invoke({"product_id": "iphone"})
    assert product["specs"] == {"حافظه": "128 گیگابایت", "رنگ": "مشکی"}
    assert product["lowest_price"] == 80_000_000
    assert get_product_details.invoke({"product_id": "nope"})["type"] == "error"


def test_compare_products_keeps_order_and_only_shared_specs(world):
    result = compare_products.invoke({"product_ids": ["pro", "iphone"]})
    assert [p["id"] for p in result["products"]] == ["pro", "iphone"]
    # "رنگ" and "وزن" exist on one product only: nothing to compare.
    assert result["specs"] == [{"key": "حافظه", "values": ["256 گیگابایت", "128 گیگابایت"]}]


@pytest.mark.parametrize("ids", [["iphone"], ["iphone", "nope"]])
def test_compare_products_needs_two_real_products(world, ids):
    assert compare_products.invoke({"product_ids": ids})["type"] == "error"


def test_explore_category_prefers_categories_starting_with_the_query(world):
    result = explore_category.invoke({"category": "یخچال"})
    # The parts category also contains "یخچال", but it is not what the user asked for.
    assert result["categories"] == [{"category_name": "یخچال فریزر ساید بای ساید", "products": 1}]
    # brand_name is empty: the brand comes from the "برند" spec.
    assert result["top_brands"] == ["سامسونگ"]


def test_explore_category_falls_back_to_contains_and_reports_unknown(world):
    result = explore_category.invoke({"category": "لوازم جانبی یخچال"})
    assert [c["category_name"] for c in result["categories"]] == ["قطعات و لوازم جانبی یخچال"]
    assert explore_category.invoke({"category": "هواپیما"})["type"] == "error"


def test_alternatives_stay_in_category_and_price_range(world):
    # iPhone lowest price 80M: window is 48M..104M. Pro (150M) is too expensive,
    # the battery is another category, and the iPhone itself is excluded.
    result = find_alternatives.invoke({"product_id": "iphone"})
    assert [p["id"] for p in result["alternatives"]] == ["samsung"]


def test_alternatives_with_budget_rank_most_similar_first(world):
    result = find_alternatives.invoke({"product_id": "iphone", "max_price": 200_000_000})
    assert [p["id"] for p in result["alternatives"]] == ["pro", "samsung"]


# --- Stores ---------------------------------------------------------------------------


def test_find_stores_nearest_first(world):
    result = run(find_stores, "iphone")
    assert names(result["stores"]) == ["A", "D", "B", "C"]
    a = result["stores"][0]
    assert a["distance_km"] == pytest.approx(0.11, abs=0.01)
    assert a["price"]["min"] == 100_000_000
    assert a["price"]["freshness"]["label"] == "fresh"


def test_find_stores_without_location_is_cheapest_first(world):
    result = run(find_stores, "iphone", context=None)
    # The store without a usable price goes last, and no distance is invented.
    assert names(result["stores"]) == ["C", "B", "A", "D"]
    assert all(store["distance_km"] is None for store in result["stores"])


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        ({"radius_km": 2}, ["A", "D", "B"]),
        ({"max_price": 95_000_000}, ["B", "C"]),
        ({"installment": True}, ["B", "C"]),
        ({"torob_pay": True}, ["B"]),
        ({"open_now": True}, ["A"]),  # B is closed, C and D have unknown hours
    ],
)
def test_find_stores_filters(world, filters, expected):
    assert names(run(find_stores, "iphone", **filters)["stores"]) == expected


def test_store_details(world):
    a = run(get_store_details, "A")
    assert a["stores_in_same_building"] == 1  # B is in mall_1 too
    assert a["categories"] == [PHONES]
    assert a["opening"]["state"] == "open"

    f = run(get_store_details, "F")
    # Iranian week order, shifts sorted even though they were stored out of order.
    assert f["weekly_hours"] == [
        {"day": "sat", "status": "declared", "shifts": ["09:00-13:00", "16:00-21:00"]},
        {"day": "fri", "status": "closed", "shifts": []},
    ]
    assert run(get_store_details, "nope")["type"] == "error"


def test_find_stores_by_category_marks_unconfirmed_stores(world):
    result = run(find_stores_by_category, PHONES)
    assert names(result["stores"]) == ["E", "A"]
    assert [s["product_list_known"] for s in result["stores"]] == [False, True]


def test_compare_stores_badges_and_warranty(world):
    result = run(compare_stores, "iphone", ["A", "B", "C", "nope"])
    stores = {s["id"]: s for s in result["stores"]}
    badges = {sid: s["badges"] for sid, s in stores.items()}

    assert [sid for sid, b in badges.items() if b["cheapest"]] == ["C"]
    assert [sid for sid, b in badges.items() if b["nearest"]] == ["A"]
    assert sorted(sid for sid, b in badges.items() if b["same_mall_as_others"]) == ["A", "B"]
    assert [sid for sid, b in badges.items() if b["open_now"]] == ["A"]
    assert stores["B"]["warranties"] == ["شرکتی (18 ماه)"]
    assert result["not_listing_this_product"] == ["nope"]


def test_compare_stores_needs_two_listing_stores(world):
    assert run(compare_stores, "iphone", ["A", "E"])["type"] == "error"


def test_store_cards_carry_the_phone_for_the_call_button(world):
    Shop.objects.filter(id="A").update(phone="02112345678")
    stores = {s["id"]: s for s in run(find_stores, "iphone")["stores"]}
    assert stores["A"]["phone"] == "02112345678"
    assert stores["B"]["phone"] is None


def test_store_results_name_their_product(world):
    # The UI names the product and shows its photo, even if it was found in an earlier message.
    iphone = {
        "id": "iphone",
        "persian_title": "گوشی آیفون 15 | حافظه 128 گیگابایت",
        "main_image": None,
    }
    assert run(find_stores, "iphone")["product"] == iphone
    assert run(compare_stores, "iphone", ["A", "B"])["product"] == iphone
    assert run(find_stores, "nope")["product"] is None

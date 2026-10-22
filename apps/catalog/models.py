from typing import TYPE_CHECKING

from django.contrib.postgres.indexes import GinIndex
from django.db import models

if TYPE_CHECKING:
    from django.db.models.fields.related_descriptors import RelatedManager


class Shop(models.Model):
    class ShopType(models.TextChoices):
        HAS_PRODUCTS = "has_products"
        CATEGORY_ONLY = "category_only"
        LOCATION_ONLY = "location_only"

    id = models.CharField(primary_key=True, max_length=40)
    name = models.TextField()
    shop_type = models.CharField(max_length=20, choices=ShopType.choices)
    lat = models.FloatField()
    lon = models.FloatField()
    address = models.TextField(null=True)
    location_label = models.TextField(null=True)
    building = models.TextField(null=True)
    building_key = models.TextField(null=True, db_index=True)
    floor = models.SmallIntegerField(null=True)
    unit = models.TextField(null=True)
    plaque = models.TextField(null=True)
    phone = models.TextField(null=True)
    website_url = models.TextField(null=True)
    instagram_url = models.TextField(null=True)
    supports_fast_delivery = models.BooleanField(null=True)

    # Reverse relations, declared only so pyright knows them.
    working_hours: "RelatedManager[ShopWorkingHours]"
    payments: "RelatedManager[ShopPayment]"

    def __str__(self):
        return self.name


class Product(models.Model):
    id = models.CharField(primary_key=True, max_length=40)
    persian_title = models.TextField(null=True)
    brand_name = models.TextField(null=True)
    model = models.TextField(null=True)
    category_name = models.TextField(db_index=True)
    main_image = models.TextField(null=True)
    image_urls = models.JSONField(null=True)
    specs = models.JSONField(default=dict)
    search_text = models.TextField()

    class Meta:
        indexes = [
            GinIndex(
                fields=["search_text"], name="product_search_trgm", opclasses=["gin_trgm_ops"]
            ),
        ]

    def __str__(self):
        return self.persian_title or self.id


class Offer(models.Model):
    class PriceStatus(models.TextChoices):
        OK = "ok"
        MISSING = "missing"
        PLACEHOLDER = "placeholder"
        TOO_HIGH = "too_high"

    id = models.CharField(primary_key=True, max_length=40)
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="offers")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="offers")
    seller_title = models.TextField()
    description = models.TextField(null=True)
    price_toman = models.BigIntegerField(null=True)
    price_status = models.CharField(max_length=20, choices=PriceStatus.choices)
    last_price_changed_at = models.DateTimeField(null=True)
    warranty_provider = models.TextField(null=True)
    warranty_period_months = models.SmallIntegerField(null=True)
    warranty_description = models.TextField(null=True)


class ShopProduct(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="shop_products")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="shop_products")
    min_price = models.BigIntegerField(null=True)  # NULL: no usable price, ask the shop
    max_price = models.BigIntegerField(null=True)
    variant_count = models.IntegerField()
    last_price_changed_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["shop", "product"], name="unique_shop_product"),
        ]


class ShopWorkingHours(models.Model):
    class Day(models.TextChoices):
        SAT = "sat"
        SUN = "sun"
        MON = "mon"
        TUE = "tue"
        WED = "wed"
        THU = "thu"
        FRI = "fri"

    class Status(models.TextChoices):
        DECLARED = "declared"
        CLOSED = "closed"
        UNSUPPORTED = "unsupported"

    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="working_hours")
    day = models.CharField(max_length=3, choices=Day.choices)
    status = models.CharField(max_length=20, choices=Status.choices)
    start_time = models.TimeField(null=True)
    end_time = models.TimeField(null=True)


class ShopPayment(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="payments")
    provider = models.TextField()
    channel = models.TextField()


class ShopCategory(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="categories")
    category = models.TextField(db_index=True)

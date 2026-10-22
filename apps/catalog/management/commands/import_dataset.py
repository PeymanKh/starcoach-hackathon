from pathlib import Path

import pyarrow.parquet as pq
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

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

TABLES = [
    (
        Shop,
        "shops",
        [
            "shop_id",
            "name",
            "shop_type",
            "lat",
            "lon",
            "address",
            "location_label",
            "building",
            "building_key",
            "floor",
            "unit",
            "plaque",
            "phone",
            "website_url",
            "instagram_url",
            "supports_fast_delivery",
        ],
    ),
    (
        Offer,
        "offers",
        [
            "offer_id",
            "shop_id",
            "product_id",
            "seller_title",
            "description",
            "price_toman",
            "price_status",
            "last_price_changed_at",
            "warranty_provider",
            "warranty_period_months",
            "warranty_description",
        ],
    ),
    (
        ShopProduct,
        "shop_products",
        [
            "shop_id",
            "product_id",
            "min_price",
            "max_price",
            "variant_count",
            "last_price_changed_at",
        ],
    ),
    (
        ShopWorkingHours,
        "shop_working_hours",
        ["shop_id", "day", "status", "start_time", "end_time"],
    ),
    (ShopPayment, "shop_payments", ["shop_id", "provider", "channel"]),
    (ShopCategory, "shop_categories", ["shop_id", "category"]),
]
ID_COLUMN = {Shop: "shop_id", Offer: "offer_id"}
PRODUCT_COLUMNS = [
    "product_id",
    "persian_title",
    "brand_name",
    "model",
    "category_name",
    "main_image",
    "image_urls",
]


def read_rows(path, columns):
    """Yield rows as tuples, 50k at a time, so the whole file is never in memory."""
    for batch in pq.ParquetFile(path).iter_batches(batch_size=50_000, columns=columns):
        yield from zip(*(batch.column(name).to_pylist() for name in columns), strict=True)


def copy_rows(cursor, table, columns, rows):
    """COPY is Postgres' bulk loader: much faster than INSERT or bulk_create."""
    with cursor.copy(f"COPY {table} ({', '.join(columns)}) FROM STDIN") as copy:
        for row in rows:
            copy.write_row(row)


class Command(BaseCommand):
    help = "Replace the catalog tables with the cleaned Torob dataset (a folder of .parquet)."

    def add_arguments(self, parser):
        parser.add_argument("path", type=Path, help="Folder with the cleaned .parquet files")

    def handle(self, *args, path, **options):
        names = ["products", "product_specs"] + [name for _, name, _ in TABLES]
        missing = [name for name in names if not (path / f"{name}.parquet").exists()]
        if missing:
            raise CommandError(f"Missing files in {path}: {', '.join(missing)}")

        models = [Product] + [model for model, _, _ in TABLES]
        tables = [model._meta.db_table for model in models]

        # All or nothing: if anything fails, the old data stays.
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(f"TRUNCATE {', '.join(tables)}")

            self.load_products(cursor, path)
            for model, name, columns in TABLES:
                db_columns = ["id" if c == ID_COLUMN.get(model) else c for c in columns]
                rows = read_rows(path / f"{name}.parquet", columns)
                copy_rows(cursor, model._meta.db_table, db_columns, rows)

            for table in tables:
                cursor.execute(f"ANALYZE {table}")  # fresh statistics for the query planner
                cursor.execute(f"SELECT count(*) FROM {table}")
                self.stdout.write(f"{table}: {cursor.fetchone()[0]:,} rows")

        self.stdout.write(self.style.SUCCESS("Dataset imported."))

    def load_products(self, cursor, path):
        def product_rows():
            for row in read_rows(path / "products.parquet", PRODUCT_COLUMNS):
                _, title, brand, model, *_ = row
                yield (*row, "{}", normalize_for_search(title, brand, model))

        columns = ["id", *PRODUCT_COLUMNS[1:], "specs", "search_text"]
        copy_rows(cursor, Product._meta.db_table, columns, product_rows())

        # Specs: load the 1.2M rows into a temp table, let Postgres build one JSON per product.
        cursor.execute(
            "CREATE TEMP TABLE tmp_specs (product_id text, key text, value text) ON COMMIT DROP"
        )
        rows = read_rows(path / "product_specs.parquet", ["product_id", "key", "value"])
        copy_rows(cursor, "tmp_specs", ["product_id", "key", "value"], rows)
        cursor.execute(f"""
            UPDATE {Product._meta.db_table} AS p SET specs = s.specs
            FROM (
                SELECT product_id, jsonb_object_agg(key, value) AS specs
                FROM tmp_specs WHERE key IS NOT NULL GROUP BY product_id
            ) AS s
            WHERE p.id = s.product_id
        """)

_CHARS = str.maketrans(
    "آأإةيك" + "۰۱۲۳۴۵۶۷۸۹" + "٠١٢٣٤٥٦٧٨٩" + "\u200c",
    "اااهیک" + "0123456789" + "0123456789" + " ",
)


def normalize_for_search(*parts: str | None) -> str:
    """Join the non-empty parts, lowercase, unify Persian letters and digits."""
    text = " ".join(part for part in parts if part).lower().translate(_CHARS)
    return " ".join(text.split())

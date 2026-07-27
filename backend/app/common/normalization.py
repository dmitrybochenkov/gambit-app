def normalize_display_name(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = " ".join(value.strip().casefold().replace("ё", "е").split())
    return normalized or None

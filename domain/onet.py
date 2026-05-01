def is_valid_onet_title(title: str | None, valid_categories_set: set[str]) -> bool:
    """
    Single definition of 'valid O*NET correction' for the pipeline.

    None is always invalid. Matching is exact and case-sensitive —
    valid_categories.csv is already title-cased by build_valid_categories.py.
    """
    if title is None:
        return False
    return title in valid_categories_set
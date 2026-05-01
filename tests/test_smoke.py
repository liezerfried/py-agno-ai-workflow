from workflows.normalization_workflow import _load_valid_categories


def test_valid_categories_csv_readable():
    categories = _load_valid_categories()
    assert len(categories) > 900, f"Expected >900 categories, got {len(categories)}"
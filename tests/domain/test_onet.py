from domain.onet import is_valid_onet_title

CATEGORIES = {"Software Engineers", "Human Resources Managers"}


def test_exact_match() -> None:
    assert is_valid_onet_title("Software Engineers", CATEGORIES) is True


def test_none_is_invalid() -> None:
    assert is_valid_onet_title(None, CATEGORIES) is False


def test_case_mismatch_is_invalid() -> None:
    assert is_valid_onet_title("software engineers", CATEGORIES) is False


def test_unknown_title_is_invalid() -> None:
    assert is_valid_onet_title("Invented Role", CATEGORIES) is False
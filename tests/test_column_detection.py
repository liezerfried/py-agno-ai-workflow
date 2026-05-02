from agents.ingest_agent import detect_job_column


def test_detect_exact_english():
    col, score = detect_job_column(["employee_id", "name", "job_category"])
    assert col == "job_category"
    assert score >= 0.85


def test_detect_spanish():
    col, score = detect_job_column(["id", "nombre", "cargo", "salario"])
    assert col == "cargo"
    assert score >= 0.85


def test_detect_with_underscores():
    col, score = detect_job_column(["emp_id", "job_title", "department"])
    assert col == "job_title"
    assert score >= 0.85


def test_detect_with_spaces():
    col, score = detect_job_column(["Employee ID", "Job Category", "Department"])
    assert col == "Job Category"
    assert score >= 0.85


def test_detect_ambiguous_returns_low_score():
    col, score = detect_job_column(["col_a", "col_b", "data"])
    assert score < 0.85


def test_detect_empty():
    col, score = detect_job_column([])
    assert col is None
    assert score == 0.0

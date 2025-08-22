from curatore_api.pipeline_adapter import score_conversion

def test_score_conversion_basic():
    md = "# Title\n\n- a\n- b\n\n| a | b |\n|---|---|\n| 1 | 2 |"
    score, fb = score_conversion(md)
    assert 0 <= score <= 100
    assert isinstance(fb, str)
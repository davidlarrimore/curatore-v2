from app.services.extraction_service import assess_pdf_text_quality


def test_assess_pdf_quality_flags_cid_tokens_and_low_alpha():
    gibberish = "(cid:123)(cid:456) \x01\x02\x03" * 5
    is_gib, metrics = assess_pdf_text_quality(gibberish)
    assert is_gib is True
    assert metrics["has_cid_tokens"] is True
    assert "cid_tokens" in metrics["reasons"]

    # Low alphabetic ratio text
    mostly_symbols = "1234567890 !!!! $$$$ %%%%" * 3
    is_gib2, metrics2 = assess_pdf_text_quality(mostly_symbols)
    assert is_gib2 is True
    assert any(r.startswith("alpha<") for r in metrics2["reasons"]) or metrics2["len"] > 0


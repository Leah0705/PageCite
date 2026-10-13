from app.pricing import compute_cost, MODEL_PRICING


def test_known_model_flash():
    cost = compute_cost("gemini-2.5-flash", 1_000_000, 1_000_000)
    # $0.30 input + $2.50 output (thinking tokens included) per 1M each
    assert abs(cost - 2.80) < 1e-9


def test_known_model_pro():
    cost = compute_cost("gemini-2.5-pro", 1_000_000, 1_000_000)
    assert abs(cost - 11.25) < 1e-9


def test_zero_tokens():
    assert compute_cost("gemini-2.5-flash", 0, 0) == 0.0


def test_unknown_model_uses_flash_default():
    default_cost = compute_cost("gemini-2.5-flash", 500, 500)
    unknown_cost = compute_cost("unknown-model-xyz", 500, 500)
    assert abs(default_cost - unknown_cost) < 1e-12


def test_embedding_model_is_free():
    assert compute_cost("sentence-transformers/all-mpnet-base-v2", 1_000_000, 0) == 0.0


def test_pricing_dict_has_expected_models():
    assert "gemini-2.5-flash" in MODEL_PRICING
    assert "gemini-2.5-pro" in MODEL_PRICING

import pytest

from app.sdk import cost as cost_module
from app.sdk.cost import calculate_cost
from app.sdk.types import Usage


def _reset_cache():
    cost_module._prices = None


def test_known_model_returns_usd():
    _reset_cache()
    usage = Usage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
    c = calculate_cost("openai/gpt-4o-mini", usage)
    # 1000 * 1.5e-7 + 500 * 6.0e-7 = 0.00015 + 0.0003 = 0.00045
    assert c == pytest.approx(0.00045, rel=1e-9)


def test_unknown_model_returns_none():
    _reset_cache()
    usage = Usage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
    assert calculate_cost("openai/imaginary-model", usage) is None


def test_zero_tokens_returns_zero():
    _reset_cache()
    usage = Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
    assert calculate_cost("openai/gpt-4o", usage) == 0.0


def test_loads_json_only_once():
    _reset_cache()
    usage = Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2)
    calculate_cost("openai/gpt-4o", usage)
    cached = cost_module._prices
    assert cached is not None
    calculate_cost("openai/gpt-4o-mini", usage)
    assert cost_module._prices is cached  # same object, no re-read


def test_catalog_locked_to_known_prices():
    """Pin the catalog so a typo in JSON fails CI loudly."""
    _reset_cache()
    prices = cost_module._load()
    assert prices["openai/gpt-4o"]["input_cost_per_token"] == 2.5e-6
    assert prices["openai/gpt-4o-mini"]["output_cost_per_token"] == 6.0e-7
    assert prices["openai/gpt-3.5-turbo"]["input_cost_per_token"] == 5.0e-7


def test_anthropic_models_present_in_catalog():
    _reset_cache()
    prices = cost_module._load()
    assert "anthropic/claude-opus-4-7" in prices
    assert "anthropic/claude-sonnet-4-6" in prices
    assert "anthropic/claude-haiku-4-5-20251001" in prices


def test_anthropic_haiku_cost_calc():
    _reset_cache()
    usage = Usage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
    c = calculate_cost("anthropic/claude-haiku-4-5-20251001", usage)
    # 1000 * 8.0e-7 + 500 * 4.0e-6 = 8e-4 + 2e-3 = 0.0028
    assert c == pytest.approx(0.0028, rel=1e-9)


def test_anthropic_catalog_pinned_prices():
    """Pin the Anthropic catalog so a typo in JSON fails CI loudly."""
    _reset_cache()
    prices = cost_module._load()
    assert prices["anthropic/claude-opus-4-7"]["input_cost_per_token"] == 1.5e-5
    assert prices["anthropic/claude-sonnet-4-6"]["output_cost_per_token"] == 1.5e-5
    assert prices["anthropic/claude-haiku-4-5-20251001"]["input_cost_per_token"] == 8.0e-7

import json
from pathlib import Path

from app.sdk.types import Usage

_PRICES_PATH = Path(__file__).parent / "model_prices.json"
_prices: dict[str, dict] | None = None


def _load() -> dict[str, dict]:
    global _prices
    if _prices is None:
        _prices = json.loads(_PRICES_PATH.read_text())
    return _prices


def calculate_cost(model: str, usage: Usage) -> float | None:
    """Compute USD cost for a usage record. Returns None if model is unknown.

    `model` is the full 'provider/bare' string, matching JSON keys.
    """
    info = _load().get(model)
    if not info:
        return None
    return (
        usage.prompt_tokens * info.get("input_cost_per_token", 0.0)
        + usage.completion_tokens * info.get("output_cost_per_token", 0.0)
    )

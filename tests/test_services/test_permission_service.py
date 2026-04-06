from app.services.permission_service import (
    model_is_allowed,
    model_matches_pattern,
    resolve_model_access,
)


# --- Task 2: Wildcard Model Matching ---


def test_exact_match():
    assert model_matches_pattern("gpt-4", "gpt-4") is True
    assert model_matches_pattern("gpt-4", "gpt-3.5") is False


def test_wildcard_suffix():
    assert model_matches_pattern("claude-3-opus", "claude-*") is True
    assert model_matches_pattern("claude-3-sonnet", "claude-*") is True
    assert model_matches_pattern("gpt-4", "claude-*") is False


def test_star_matches_all():
    assert model_matches_pattern("anything", "*") is True
    assert model_matches_pattern("gpt-4-turbo", "*") is True


def test_case_sensitive():
    assert model_matches_pattern("GPT-4", "gpt-4") is False
    assert model_matches_pattern("Claude-3", "claude-*") is False


def test_model_is_allowed_with_list():
    assert model_is_allowed("gpt-4", ["gpt-4", "claude-*"]) is True
    assert model_is_allowed("claude-3-opus", ["gpt-4", "claude-*"]) is True
    assert model_is_allowed("llama-70b", ["gpt-4", "claude-*"]) is False


def test_model_is_allowed_star():
    assert model_is_allowed("anything", ["*"]) is True


def test_model_is_allowed_empty_list_denies():
    assert model_is_allowed("gpt-4", []) is False


def test_model_is_allowed_none_inherits():
    assert model_is_allowed("gpt-4", None) is None


# --- Task 3: Resolution Chain ---


def test_resolve_key_level_allows():
    assert (
        resolve_model_access(
            "gpt-4", key_allowed_models=["gpt-4", "claude-*"], team_allowed_models=None
        )
        is True
    )


def test_resolve_key_level_denies():
    assert (
        resolve_model_access(
            "llama-70b", key_allowed_models=["gpt-4"], team_allowed_models=["*"]
        )
        is False
    )


def test_resolve_inherits_to_team():
    assert (
        resolve_model_access(
            "gpt-4", key_allowed_models=None, team_allowed_models=["gpt-4"]
        )
        is True
    )


def test_resolve_team_denies():
    assert (
        resolve_model_access(
            "llama-70b", key_allowed_models=None, team_allowed_models=["gpt-4"]
        )
        is False
    )


def test_resolve_both_none_allows():
    assert (
        resolve_model_access(
            "anything", key_allowed_models=None, team_allowed_models=None
        )
        is True
    )


def test_resolve_empty_key_list_denies():
    assert (
        resolve_model_access(
            "gpt-4", key_allowed_models=[], team_allowed_models=["*"]
        )
        is False
    )

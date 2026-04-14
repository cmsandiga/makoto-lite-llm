"""Permission service — pure functions for model access control.

Provides wildcard/glob-style pattern matching for model names and a
resolution chain that checks key → team → allow-all.
"""


def model_matches_pattern(model: str, pattern: str) -> bool:
    """Check if a model name matches a glob-style pattern.

    - Exact match: "gpt-4" matches "gpt-4"
    - Wildcard suffix: "claude-*" matches "claude-3-opus"
    - Match all: "*" matches everything
    - Case-sensitive
    """
    if pattern == "*":
        return True
    if pattern.endswith("*"):
        return model.startswith(pattern[:-1])
    return model == pattern


def model_is_allowed(model: str, allowed_models: list[str] | None) -> bool | None:
    """Check if a model is in an allowed_models list.

    Returns:
        True  — model explicitly allowed by at least one pattern
        False — model not matched by any pattern (denied)
        None  — allowed_models is None, meaning inherit from parent
    """
    if allowed_models is None:
        return None
    return any(model_matches_pattern(model, pattern) for pattern in allowed_models)


def resolve_model_access(
    model: str,
    key_allowed_models: list[str] | None,
    team_allowed_models: list[str] | None,
    org_allowed_models: list[str] | None = None,
) -> bool:
    """Resolve whether a model is accessible through the inheritance chain.

    Resolution order: key → team → org → allow-all.
    If all levels return None (i.e. allowed_models is None),
    the model is allowed by default.
    """
    key_result = model_is_allowed(model, key_allowed_models)
    if key_result is not None:
        return key_result

    team_result = model_is_allowed(model, team_allowed_models)
    if team_result is not None:
        return team_result

    org_result = model_is_allowed(model, org_allowed_models)
    if org_result is not None:
        return org_result

    return True

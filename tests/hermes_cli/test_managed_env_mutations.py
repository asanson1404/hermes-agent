"""Managed policy survives generic writers and reloads in each profile context."""
import os
from pathlib import Path

import pytest


@pytest.fixture(params=["default", "named", "launch-scoped", "routed"])
def env_context(request, tmp_path, monkeypatch):
    from agent.secret_scope import reset_secret_scope, set_secret_scope
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    from hermes_cli import config, managed_scope

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    launch = tmp_path / ".hermes"
    named = launch / "profiles" / "work"
    managed = tmp_path / "managed"
    for path in (launch, named, managed):
        path.mkdir(parents=True, exist_ok=True)
    home = launch if request.param in ("default", "launch-scoped") else named
    monkeypatch.setenv("HERMES_HOME", str(launch if request.param == "routed" else home))
    monkeypatch.setenv("HERMES_MANAGED_DIR", str(managed))
    monkeypatch.delenv("HERMES_MANAGED", raising=False)
    managed_scope.invalidate_managed_cache()
    config.invalidate_env_cache()
    scope = {} if request.param in ("launch-scoped", "routed") else None
    scope_token = set_secret_scope(scope, profile_home=str(home))
    home_token = set_hermes_home_override(home if scope is not None else None)
    try:
        yield home, managed, scope, request.param == "routed"
    finally:
        reset_hermes_home_override(home_token)
        reset_secret_scope(scope_token)
        config.invalidate_env_cache()
        managed_scope.invalidate_managed_cache()


@pytest.mark.parametrize("operation", ["save", "remove", "publish", "unpublish", "validate", "secure", "credential-remove"])
@pytest.mark.parametrize("launch_override", [True, False])
def test_launch_only_key_cannot_be_mutated(env_context, tmp_path, monkeypatch, operation, launch_override):
    from hermes_cli import config, managed_scope
    from hermes_cli.credential_lifecycle import remove_provider_env_credential

    home, managed, scope, _ = env_context
    env_path = home / ".env"
    original = "DUMMY_PERSONAL_TOKEN=retained\nHERMES_MANAGED_DIR=legacy-ignored\n"
    env_path.write_text(original, encoding="utf-8")
    alternative = tmp_path / "alternative"
    alternative.mkdir()
    key = "HERMES_MANAGED_DIR"
    if not launch_override:
        monkeypatch.delenv(key)
    operations = {
        "save": lambda: config.save_env_value(key, str(alternative)),
        "remove": lambda: config.remove_env_value(key),
        "publish": lambda: config._publish_env_value(key, str(alternative)),
        "unpublish": lambda: config._publish_env_value(key, None),
        "validate": lambda: config.validate_env_var_name_for_write(key),
        "secure": lambda: config.save_env_value_secure(key, str(alternative)),
        "credential-remove": lambda: remove_provider_env_credential(key),
    }
    if operation in ("validate", "secure", "credential-remove"):
        with pytest.raises(ValueError, match="launch"):
            operations[operation]()
    else:
        result = operations[operation]()
        if operation == "remove":
            assert result is False
    assert env_path.read_text(encoding="utf-8") == original
    assert os.environ.get(key) == (str(managed) if launch_override else None)
    assert managed_scope.get_managed_dir() == (managed if launch_override else None)
    assert scope is None or key not in scope


def test_reload_keeps_managed_last_and_profile_local(env_context, monkeypatch):
    from agent.secret_scope import build_profile_secret_scope
    from hermes_cli import config, env_loader

    home, managed, scope, routed = env_context
    (managed / ".env").write_text(
        "SLACK_ALLOWED_USERS=admin-owner\nGITHUB_TOKEN=dummy-managed\n", encoding="utf-8"
    )
    (home / ".env").write_text(
        "SLACK_ALLOWED_USERS=personal-owner\nDUMMY_PERSONAL_TOKEN=personal-only\n"
        "OPENAI_API_KEY=op://dummy/reference\nHERMES_MANAGED_DIR=ignored\n", encoding="utf-8"
    )
    # External sources have already hydrated; reload must retain their resolved values,
    # without performing a provider/network refresh or allowing them to beat admin policy.
    monkeypatch.setattr(env_loader, "get_secret_source_values", lambda path: {
        "OPENAI_API_KEY": "dummy-resolved", "SLACK_ALLOWED_USERS": "external-owner",
    })
    for key in ("SLACK_ALLOWED_USERS", "GITHUB_TOKEN", "OPENAI_API_KEY", "DUMMY_PERSONAL_TOKEN", "ANTHROPIC_API_KEY"):
        monkeypatch.setenv(key, "launch-original")
    if scope is not None:
        scope.update(ANTHROPIC_API_KEY="stale", SLACK_ALLOWED_USERS="stale")
    original_process = dict(os.environ)
    original_file = (home / ".env").read_bytes()

    assert config.reload_env() > 0
    target = scope if scope is not None else os.environ
    assert target["SLACK_ALLOWED_USERS"] == "admin-owner"
    assert target["GITHUB_TOKEN"] == "dummy-managed"
    assert target["OPENAI_API_KEY"] == "dummy-resolved"
    assert target["DUMMY_PERSONAL_TOKEN"] == "personal-only"
    assert "ANTHROPIC_API_KEY" not in target
    assert os.environ["HERMES_MANAGED_DIR"] == str(managed)
    assert (home / ".env").read_bytes() == original_file
    assert build_profile_secret_scope(home)["SLACK_ALLOWED_USERS"] == "admin-owner"
    if routed:
        assert dict(os.environ) == original_process
    else:
        assert os.environ["SLACK_ALLOWED_USERS"] == "admin-owner"
        assert os.environ["OPENAI_API_KEY"] == "dummy-resolved"
    assert config.reload_env() == 0


def test_personal_key_save_delete_reload_stays_local(env_context, monkeypatch):
    from agent.secret_scope import build_profile_secret_scope
    from hermes_cli import config

    home, managed, scope, routed = env_context
    (managed / ".env").write_text("SLACK_ALLOWED_USERS=admin-owner\n", encoding="utf-8")
    (home / ".env").write_text("DUMMY_EXISTING_TOKEN=retained\n", encoding="utf-8")
    monkeypatch.setenv("DUMMY_NEW_TOKEN", "launch-only-personal")
    original_process = dict(os.environ)
    target = scope if scope is not None else os.environ
    config.save_env_value("DUMMY_NEW_TOKEN", "dummy-new-value")
    assert config.load_env()["DUMMY_NEW_TOKEN"] == "dummy-new-value"
    assert target["DUMMY_NEW_TOKEN"] == "dummy-new-value"
    config.reload_env()
    assert target["DUMMY_NEW_TOKEN"] == "dummy-new-value"
    assert config.remove_env_value("DUMMY_NEW_TOKEN") is True
    assert "DUMMY_NEW_TOKEN" not in config.load_env()
    assert "DUMMY_NEW_TOKEN" not in target
    config.reload_env()
    assert "DUMMY_NEW_TOKEN" not in target
    assert config.load_env() == {"DUMMY_EXISTING_TOKEN": "retained"}
    assert build_profile_secret_scope(home)["SLACK_ALLOWED_USERS"] == "admin-owner"
    config.save_env_value("SLACK_ALLOWED_USERS", "personal-owner")
    assert config.remove_env_value("SLACK_ALLOWED_USERS") is False
    assert target["SLACK_ALLOWED_USERS"] == "admin-owner"
    if routed:
        assert dict(os.environ) == original_process

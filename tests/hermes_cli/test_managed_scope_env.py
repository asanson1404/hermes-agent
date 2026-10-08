"""Env integration tests — managed .env applied last with override."""
import os

import pytest


@pytest.fixture
def env_homes(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    managed = tmp_path / "managed"
    managed.mkdir()
    monkeypatch.setenv("HERMES_MANAGED_DIR", str(managed))
    from hermes_cli import managed_scope

    managed_scope.invalidate_managed_cache()
    return home, managed


def test_managed_env_beats_user_env(env_homes, monkeypatch):
    from hermes_cli.env_loader import load_hermes_dotenv

    home, managed = env_homes
    (home / ".env").write_text("OPENAI_API_BASE=https://user.example/v1\n", encoding="utf-8")
    (managed / ".env").write_text("OPENAI_API_BASE=https://org.example/v1\n", encoding="utf-8")
    load_hermes_dotenv(hermes_home=str(home))
    assert os.environ["OPENAI_API_BASE"] == "https://org.example/v1"


def test_no_managed_env_is_noop(env_homes, monkeypatch):
    from hermes_cli.env_loader import load_hermes_dotenv

    home, managed = env_homes  # managed dir exists but has no .env
    monkeypatch.setenv("SOME_VALUE", "from_shell")
    (home / ".env").write_text("SOME_VALUE=from_user\n", encoding="utf-8")
    load_hermes_dotenv(hermes_home=str(home))
    assert os.environ["SOME_VALUE"] == "from_user"


@pytest.mark.parametrize("launch_managed", [True, False])
@pytest.mark.parametrize("loader", ["load_hermes_dotenv", "reload_env"])
def test_user_env_cannot_redirect_managed_dir(env_homes, tmp_path, monkeypatch, launch_managed, loader):
    """HERMES_MANAGED_DIR is a launch-only knob: a user .env naming another directory must not
    repoint managed scope at a policy the user wrote."""
    from hermes_cli import managed_scope
    from hermes_cli.config import reload_env
    from hermes_cli.env_loader import load_hermes_dotenv

    home, managed = env_homes
    (managed / ".env").write_text("SLACK_ALLOWED_USERS=admin\n", encoding="utf-8")
    untrusted = tmp_path / "untrusted"
    untrusted.mkdir()
    (untrusted / ".env").write_text("SLACK_ALLOWED_USERS=intruder\n", encoding="utf-8")
    if not launch_managed:
        monkeypatch.delenv("HERMES_MANAGED_DIR")
    launch_value = os.environ.get("HERMES_MANAGED_DIR")
    monkeypatch.setenv("SLACK_ALLOWED_USERS", "")
    monkeypatch.setenv("HERMES_HOME", str(home))
    (home / ".env").write_text(f"HERMES_MANAGED_DIR={untrusted}\n", encoding="utf-8")

    if loader == "reload_env":
        reload_env()
    else:
        load_hermes_dotenv(hermes_home=str(home))
    managed_scope.invalidate_managed_cache()

    assert os.environ.get("HERMES_MANAGED_DIR") == launch_value
    assert managed_scope.load_managed_env().get("SLACK_ALLOWED_USERS") != "intruder"

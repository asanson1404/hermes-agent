"""Managed policy composes with personal credentials, without ambient leaks."""
import pytest

from agent import secret_scope as ss
from hermes_cli import managed_scope


@pytest.mark.parametrize("personal_gate", [None, "USER-COLLISION"])
def test_managed_credentials_resolve_across_profiles(tmp_path, monkeypatch, personal_gate):
    managed = tmp_path / "managed"
    managed.mkdir()
    (managed / ".env").write_text(
        "SLACK_ALLOWED_USERS=ADMIN\nMANAGED_ONLY_KEY=managed-value\n"
        "PATH=not-a-secret-path\nTERMINAL_CWD=not-a-secret-cwd\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_MANAGED_DIR", str(managed))
    monkeypatch.setenv("SLACK_MCP_CLIENT_SECRET", "ambient-must-not-leak")
    monkeypatch.setenv("PATH", "process-path")
    homes = [tmp_path / "alice", tmp_path / "bob"]
    for home in homes:
        home.mkdir()
    personal = "SLACK_MCP_CLIENT_SECRET=alice-personal\n"
    if personal_gate is not None:
        personal += f"SLACK_ALLOWED_USERS={personal_gate}\n"
    (homes[0] / ".env").write_text(personal, encoding="utf-8")
    managed_scope.invalidate_managed_cache()
    previous_mode = ss.is_multiplex_active()
    ss.set_multiplex_active(True)
    try:
        for home, expected in [(homes[0], "alice-personal"), (homes[1], None),
                               (homes[0], "alice-personal")]:
            scope = ss.build_profile_secret_scope(home)
            token = ss.set_secret_scope(scope, profile_home=str(home))
            try:
                assert ss.get_secret("MANAGED_ONLY_KEY") == "managed-value"
                assert ss.get_secret("SLACK_ALLOWED_USERS") == "ADMIN"
                assert ss.get_secret("SLACK_MCP_CLIENT_SECRET") == expected
                assert "PATH" not in scope
                assert "TERMINAL_CWD" not in scope
                assert ss.get_secret("PATH") == "process-path"
            finally:
                ss.reset_secret_scope(token)
    finally:
        ss.set_multiplex_active(previous_mode)
        managed_scope.invalidate_managed_cache()


@pytest.mark.parametrize("multiplex", [False, True])
@pytest.mark.parametrize("empty_managed_dir", [False, True])
def test_unmanaged_profile_retains_existing_resolution(
    tmp_path, monkeypatch, multiplex, empty_managed_dir
):
    managed = tmp_path / "no-managed-env"
    if empty_managed_dir:
        managed.mkdir()
    monkeypatch.setenv("HERMES_MANAGED_DIR", str(managed))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("AMBIENT_ONLY_KEY", "process-value")
    (tmp_path / ".env").write_text("SLACK_MCP_CLIENT_SECRET=personal\n", encoding="utf-8")
    previous_mode = ss.is_multiplex_active()
    ss.set_multiplex_active(multiplex)
    token = ss.set_secret_scope(ss.build_profile_secret_scope(tmp_path), profile_home=str(tmp_path))
    try:
        assert ss.get_secret("SLACK_MCP_CLIENT_SECRET") == "personal"
        assert ss.get_secret("AMBIENT_ONLY_KEY") == (None if multiplex else "process-value")
        assert ss.get_secret("SLACK_ALLOWED_USERS") is None
    finally:
        ss.reset_secret_scope(token)
        ss.set_multiplex_active(previous_mode)

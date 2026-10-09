"""Docker's prepared dependency selection must survive the first plugin sync."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_image_build_retains_features_for_plugin_sync(tmp_path, monkeypatch):
    from docker import build_dependencies
    import pm
    import pm.install as install
    from pm import paths
    from pm.environments import runtime_facts_path
    from pm.features import read_features
    from pm.lock import Facts
    from pm.plugin_inputs import Members

    root = tmp_path / "image"
    root.mkdir()
    built = []

    def build(**kwargs):
        built.extend(kwargs["extras"])
        return root / ".venv/bin/python"

    monkeypatch.setattr(pm, "build_environment", build)
    build_dependencies.build_image_dependencies(root, Path("/usr/local/bin/python3"))
    monkeypatch.setattr(paths, "store_root", lambda: root / "tools")
    monkeypatch.setattr(paths, "repo_root", lambda: root)
    assert read_features() == sorted(built)
    assert {"all", "messaging", "matrix", "google-chat"} <= set(built)
    (root / "pyproject.toml").write_text(
        "[project]\nname='fixture'\nversion='1'\n[project.optional-dependencies]\n"
        + "\n".join(f"{name}=[]" for name in [*built, "mcp", "slack"])
    )
    monkeypatch.setattr(install, "lazy_installs_allowed", lambda: True)
    package = install.get_package("venv")
    monkeypatch.setattr(package, "expected_stamp", lambda extras, **kw: json.dumps(extras))
    selections = []

    def apply(extras, **kwargs):
        selections.append((extras, kwargs))
        return {}

    monkeypatch.setattr(package, "apply", apply)
    plugin = root / "plugin"
    plugin.mkdir()
    install.sync_venv(explicit=True, plugins=Members([plugin]))
    assert selections[-1][0] == sorted(built)
    assert selections[-1][1]["plugin_dirs"] == [plugin]
    assert Facts(runtime_facts_path(root)).get("venv")["extras"] == sorted(built)

    # An already repaired volume owns its selection; image defaults are not
    # forced back on it when a subsequent plugin transaction runs.
    Facts(runtime_facts_path(root)).record_state("venv", "repaired", ["mcp", "slack"])
    install.sync_venv(explicit=True, plugins=Members([plugin]))
    assert selections[-1][0] == ["mcp", "slack"]
    assert selections[-1][1]["plugin_dirs"] == [plugin]
    assert Facts(runtime_facts_path(root)).get("venv")["extras"] == ["mcp", "slack"]


def test_failed_image_dependency_build_does_not_publish_features(tmp_path, monkeypatch):
    from docker import build_dependencies
    import pm

    def fail(**kwargs):
        raise OSError("fixture build failure")

    monkeypatch.setattr(pm, "build_environment", fail)
    with pytest.raises(OSError, match="fixture build failure"):
        build_dependencies.build_image_dependencies(tmp_path, Path("/usr/local/bin/python3"))
    assert not (tmp_path / "enabled-features.json").exists()

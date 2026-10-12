"""Build the image dependencies and publish their PM feature baseline."""
from __future__ import annotations

from pathlib import Path

import pm


IMAGE_EXTRAS = (
    "all", "messaging", "otlp", "anthropic", "bedrock", "azure-identity",
    "matrix", "google-chat",
)


def build_image_dependencies(root: Path, python: Path) -> Path:
    """Keep the build selection and the first runtime sync's baseline identical."""
    executable = pm.build_environment(
        source=root, out=root / ".venv", python=python,
        extras=list(IMAGE_EXTRAS), no_install_project=True, sealed=True,
        explicit=True,
    )
    from pm.features import installed_extras, write_features

    # A writable generation replaces the sealed venv, rather than layering on
    # it. Publish only after a successful build. With lazy installs off this
    # list is the frozen set, so it also carries the members the aggregates
    # installed (`--extra mcp` must pass); the inventory alone would drop the
    # aggregates themselves, whose anchors are not modules.
    installed = installed_extras(root, root / ".venv", python_exe=python)
    write_features(sorted({*IMAGE_EXTRAS, *installed}), root)
    return executable


if __name__ == "__main__":
    build_image_dependencies(Path("/opt/hermes"), Path("/usr/local/bin/python3"))

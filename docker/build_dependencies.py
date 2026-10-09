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
    from pm.features import write_features

    # A writable generation replaces the sealed venv, rather than layering on
    # it. Publish only after a successful build, using the same explicit extras.
    write_features(list(IMAGE_EXTRAS), root)
    return executable


if __name__ == "__main__":
    build_image_dependencies(Path("/opt/hermes"), Path("/usr/local/bin/python3"))

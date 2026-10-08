"""Profile-local hot reload of personal, external and managed env values."""
import os
from collections.abc import MutableMapping


def reload_env() -> int:
    """Reload effective env values; count changed names, not individual mirrors.

    External providers have already hydrated their per-home snapshot. Fresh
    personal values beat non-authoritative snapshots; only authoritative source
    values may override them (including resolved op:// references). Administrator
    policy stays last. Routed requests never publish into the shared process env.
    """
    from agent.secret_scope import current_secret_scope, serves_routed_profile
    from hermes_cli import config
    from hermes_cli.env_loader import get_secret_source_values
    from hermes_constants import LAUNCH_ONLY_ENV_KEYS, get_hermes_home

    home = get_hermes_home()
    values = get_secret_source_values(home)
    values.update(config.load_env())
    values.update(get_secret_source_values(home, authoritative_only=True))
    values.update(config.managed_scope.load_managed_env())
    scope = current_secret_scope()
    targets: list[MutableMapping[str, str]] = [scope] if isinstance(scope, dict) else []
    if not serves_routed_profile() and (scope is None or isinstance(scope, dict)):
        targets.append(os.environ)
    known = set(config.OPTIONAL_ENV_VARS) | config._EXTRA_ENV_KEYS
    changed = set()
    for key in set(values) | known:
        if config._env_var_policy_name(key) in LAUNCH_ONLY_ENV_KEYS:
            continue
        for target in targets:
            if key in values:
                if target.get(key) != values[key]:
                    target[key] = values[key]
                    changed.add(key)
            elif key in target:
                del target[key]
                changed.add(key)
    return len(changed)

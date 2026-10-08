# Deploying managed gates alongside personal secrets

This fork ports only the `agent/secret_scope.py` change from upstream
`b543b1053c55e7b669639bb7f3d9610766f3e1b6` (author: kshitijk4poor).
It composes administrator `.env` values **last** in each profile secret scope,
after personal values, external sources, and the default-profile allow-all bridge.
Process-global names from the managed layer are excluded. It does not introduce
an ambient environment fallback under multiplexing or change Google MCP OAuth.

## Required Infra follow-up (not performed by this code change)

- Replace the existing admin `gates.env` bind at `/opt/data/.env` with a read-only
  bind at `/etc/hermes/.env:ro`. Keep `/etc/hermes` administrator-owned and
  non-writable by the application user; do not allow an employee-controlled
  `HERMES_MANAGED_DIR` override in the launcher.
- Keep `HERMES_HOME=/opt/data` on a persistent, writable volume. `/opt/data/.env`
  is a **separate personal file**, not a symlink or bind to the managed source.
  Named profiles retain their own `<profile-home>/.env`.
- Admin source: owner root/administrator, mode `0640` with a dedicated runtime
  read group (or `0600` if the deployment UID can legitimately read it). Validate
  the actual container UID/GID can read, but cannot replace or modify, the file.
  Personal file: runtime-user owned, mode `0600`; parent profile directories
  private (`0700`) and writable by that user for atomic replacement.
- Before changing mounts, securely preserve any underlying personal file hidden
  by the old bind. Never copy `gates.env` over personal keys; never truncate an
  existing personal `.env`. Create an empty personal file only if absent. Review
  colliding names without printing values; managed values intentionally win.
- Update **Infra backup/sync exclusions before rollout**: exclude `.env` and
  `.env.*` at the default home and every profile, admin `gates.env`, secret-manager
  exports, credential pools, OAuth/token stores (including `auth.json`), vault
  files, and copies/staging archives containing them from general backups,
  Git snapshots, diagnostics, and image build contexts. Audit the actual backup
  manifests and restore paths, not only `.gitignore`; keep any required recovery
  copy in a separately authorized encrypted secret-backup workflow. Confirm
  exclusions with dummy files, never by dumping production credentials.
- Build an image from the reviewed fork commit on top of
  `byzantine/google-mcp-oauth-v2026.9.24`, preserving its Google OAuth patches.
  Record the source SHA, run regression tests, publish through the authorized
  image pipeline, then pin an immutable image digest in a separately reviewed
  Infra change. A source PR alone does not update a running container.
- Roll out to a canary first. Record the old digest and mounts for rollback;
  preserve the personal volume on rollback. Restart only through the approved
  deployment procedure after mounts and image pin are reviewed.

## Employee acceptance in the canary UI

1. As an employee, add `SLACK_MCP_CLIENT_SECRET` via Dashboard → Keys → Custom
   Keys. Use a test credential, save, reload, and confirm it is listed masked.
   Verify an existing unrelated personal key survives and the managed file is
   unchanged. Recreate the container and confirm the saved key persists.
2. Exercise the actual Slack MCP workflow in that employee's profile. Switch to
   a second profile and back (A → B → A): the personal secret must not appear or
   work in B, and A must still work. Confirm the existing Google OAuth flow too.
3. With controlled test users, confirm the managed `SLACK_ALLOWED_USERS` policy
   remains effective even when a personal file contains a conflicting value.
   Check denied as well as allowed access; UI read-only badges alone are not
   authorization proof. Do not expose secret values in acceptance evidence.

## Boundaries and remaining risks

Local tests exercise real scope composition and the in-process dashboard API,
not a browser, container mounts, Slack network authentication, or fleet rollout.
Managed values apply to **every** profile in the process: put only intentionally
shared administrator values there, never an employee's private credential.
The existing managed loader is fail-open on absent/unreadable/malformed files;
this patch does not harden that behavior. Deployment must independently verify
managed policy is readable and applied before admitting traffic. Filesystem
permissions/read-only mounts are the enforcement boundary, not protection
against a hostile runtime with root, arbitrary code execution, or control of
launcher environment. This is not a complete sandbox or a fleet-wide fix.

The port excludes globals from the **managed** layer only. Existing personal
`.env` loading may retain global-named entries in its mapping; `get_secret`
continues resolving those names from the process environment. No broader global
filtering or policy enforcement redesign is included here.

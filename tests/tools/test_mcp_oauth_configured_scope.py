"""A configured ``oauth.scope`` must survive the SDK's scope selection.

On a 401 the SDK overwrites ``client_metadata.scope`` with the MCP spec's priority (the
``WWW-Authenticate`` scope, else the PRM ``scopes_supported``, else the AS ``scopes_supported``).
Google's hosted MCP servers advertise every Gmail scope in their PRM, ``https://mail.google.com/``
and ``gmail.send`` included, so a server configured with ``gmail.readonly`` was granted full
mailbox access. The operator's scope is an explicit restriction: it is what gets requested.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

pytest.importorskip("mcp.client.auth.oauth2")

RESOURCE = "https://res.example/mcp"
AS_ORIGIN = "https://as.example"
ADVERTISED_SCOPES = ["read", "write", "admin"]


class _StandIn:
    def __init__(self, httpx, www_scope=None):
        self.httpx, self.www_scope = httpx, www_scope

    def __call__(self, request):
        url = str(request.url)
        j = lambda status, body, **h: self.httpx.Response(status, json=body, headers=h, request=request)  # noqa: E731
        if url == RESOURCE:
            if request.headers.get("Authorization") == "Bearer AT-1":
                return j(200, {"ok": True})
            challenge = 'Bearer resource_metadata="https://res.example/.well-known/oauth-protected-resource"'
            if self.www_scope:
                challenge += f', scope="{self.www_scope}"'
            return j(401, {}, **{"WWW-Authenticate": challenge})
        if url == "https://res.example/.well-known/oauth-protected-resource":
            return j(200, {"resource": RESOURCE, "authorization_servers": [AS_ORIGIN],
                           "scopes_supported": ADVERTISED_SCOPES})
        if url == f"{AS_ORIGIN}/.well-known/oauth-authorization-server":
            return j(200, {"issuer": AS_ORIGIN, "authorization_endpoint": f"{AS_ORIGIN}/authorize",
                           "token_endpoint": f"{AS_ORIGIN}/token", "response_types_supported": ["code"],
                           "code_challenge_methods_supported": ["S256"]})
        if url == f"{AS_ORIGIN}/token":
            return j(200, {"access_token": "AT-1", "token_type": "Bearer", "expires_in": 3600, "refresh_token": "RT-1"})
        return j(404, {})


async def _authorize_scope(tmp_path, monkeypatch, configured_scope, www_scope=None):
    from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata
    from pydantic import AnyUrl

    from tools.mcp_oauth import HermesTokenStorage, _authorization_code_result
    from tools.mcp_oauth_manager import _HERMES_PROVIDER_CLS, reset_manager_for_tests
    from tools.mcp_tool import sdk_httpx

    httpx = sdk_httpx()
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    reset_manager_for_tests()
    seen = {}

    async def redirect(url):
        seen["scope"] = parse_qs(urlsplit(url).query).get("scope", [None])[0]
        seen["state"] = parse_qs(urlsplit(url).query)["state"][0]

    async def callback():
        return _authorization_code_result("code-1", seen["state"])

    redirect_uri = AnyUrl("http://127.0.0.1:1/cb")
    metadata = OAuthClientMetadata(redirect_uris=[redirect_uri], client_name="Hermes Agent", scope=configured_scope)
    storage = HermesTokenStorage("srv")
    # Pre-registered client, as with `oauth.client_id`: no dynamic registration.
    await storage.set_client_info(OAuthClientInformationFull(client_id="pre-1", redirect_uris=[redirect_uri]))
    provider = _HERMES_PROVIDER_CLS(
        server_name="srv", server_url=RESOURCE, storage=storage, client_metadata=metadata,
        redirect_handler=redirect, callback_handler=callback, preregistered=True)
    async with httpx.AsyncClient(auth=provider, transport=httpx.MockTransport(_StandIn(httpx, www_scope))) as client:
        response = await client.get(RESOURCE)
    assert response.status_code == 200
    return seen["scope"]


@pytest.mark.asyncio
async def test_configured_scope_wins_over_prm_scopes_supported(tmp_path, monkeypatch):
    assert await _authorize_scope(tmp_path, monkeypatch, "read") == "read"


@pytest.mark.asyncio
async def test_configured_scope_wins_over_www_authenticate_scope(tmp_path, monkeypatch):
    assert await _authorize_scope(tmp_path, monkeypatch, "read", www_scope="read write") == "read"


@pytest.mark.asyncio
async def test_without_configured_scope_the_sdk_selection_is_kept(tmp_path, monkeypatch):
    assert await _authorize_scope(tmp_path, monkeypatch, None) == " ".join(ADVERTISED_SCOPES)

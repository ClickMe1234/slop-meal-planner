# Authentik authentication

Slop supports one authentication mode per installation:

- `builtin` keeps the existing local username/password login and is the safe
  default.
- `authentik_proxy` uses Authentik's proxy/outpost forward-auth headers.
- `authentik_oidc` uses a confidential server-side OAuth2/OIDC authorization
  code flow with PKCE.

Authentik authenticates people; Slop remains the source of truth for whether a
local account exists, its role, household, member link, preferences, and
planning profile. External modes never provision a Slop user or expose a
password fallback.

## Prepare the installation

1. Create and verify a backup while `MEAL_PLANNER_AUTH_MODE=builtin`.
2. Create the owner and every collaborator in Slop. Set their local roles and
   member links before changing authentication mode.
3. Make each Slop username exactly match Authentik's `preferred_username` (OIDC)
   or `X-authentik-username` (proxy). Matching is case-insensitive only during
   first linking; later logins use the stable external subject/UID.
4. Confirm that the reverse proxy, Authentik, and Slop use HTTPS. Set
   `MEAL_PLANNER_COOKIE_SECURE=true`, add the public names to
   `MEAL_PLANNER_ALLOWED_HOSTS`, and enable HSTS only after HTTPS is working.
5. Configure one of the modes below, restart Slop, and test from a private
   browser window.

If an external login fails, no local account is created. Unknown, inactive,
ambiguous, or conflicting identities are denied with an actionable error. To
recover, set `MEAL_PLANNER_AUTH_MODE=builtin` and restart; this does not delete
users, passwords, identity links, or household data.

## Shared environment settings

The Compose names are shown below. Unraid exposes the same values with the
`MEAL_PLANNER_` names in [`deploy/unraid-template.xml`](../deploy/unraid-template.xml).
Inactive-mode values may remain blank.

```dotenv
MEAL_PLANNER_AUTH_MODE=builtin
MEAL_PLANNER_ALLOWED_HOSTS=localhost,127.0.0.1,slop.example.com
MEAL_PLANNER_COOKIE_SECURE=true
MEAL_PLANNER_HSTS_ENABLED=true
```

External URLs must use HTTPS except for explicit localhost development URLs.
Slop rejects embedded credentials, queries, fragments, and unsafe logout
redirects. Keep the proxy shared secret and OIDC client secret in a password
manager; never put them in a browser, URL, proxy access log, or committed file.

## Proxy/outpost mode

Set these values in `deploy/.env` or the equivalent container environment:

```dotenv
AUTH_MODE=authentik_proxy
AUTHENTIK_PROXY_INSTANCE_URL=https://auth.example.com
AUTHENTIK_PROXY_APP_SLUG=slop
AUTHENTIK_PROXY_SHARED_SECRET=<at-least-32-random-characters>
AUTHENTIK_PROXY_LOGOUT_URL=/outpost.goauthentik.io/sign_out
```

Create an Authentik Proxy Provider and application for Slop. Prefer a
single-application forward-auth setup. The configured app slug must equal the
value Authentik sends as `X-authentik-meta-app`.

The proxy must authenticate the request before it reaches Slop and inject the
headers returned by the Authentik outpost:

```text
X-authentik-uid
X-authentik-username
X-authentik-meta-app
```

It must also inject the independently configured
`X-Slop-Auth-Proxy-Secret`. Strip all four headers from the client request
before adding the trusted values. Slop validates the secret and all identity
headers when the session is exchanged and on every protected request. Authentik
headers alone are not trusted.

For domain-level forward auth, set an absolute
`AUTHENTIK_PROXY_LOGOUT_URL` on the same Authentik origin if the default outpost
path is not suitable. The absolute URL must remain on the configured
`AUTHENTIK_PROXY_INSTANCE_URL` origin.

### Nginx or Nginx Proxy Manager pattern

Use the official Authentik outpost integration for the `auth_request` endpoint.
The important safety properties are the internal auth subrequest, copied
response headers, client-header clearing, and a secret injected only by the
proxy configuration:

```nginx
location /outpost.goauthentik.io/ {
    proxy_pass http://authentik_outpost;
    proxy_set_header Host $host;
    proxy_set_header X-Original-URL $scheme://$http_host$request_uri;
}

location / {
    auth_request /outpost.goauthentik.io/auth;
    auth_request_set $authentik_uid $upstream_http_x_authentik_uid;
    auth_request_set $authentik_username $upstream_http_x_authentik_username;
    auth_request_set $authentik_app $upstream_http_x_authentik_meta_app;

    proxy_set_header X-authentik-uid $authentik_uid;
    proxy_set_header X-authentik-username $authentik_username;
    proxy_set_header X-authentik-meta-app $authentik_app;
    proxy_set_header X-Slop-Auth-Proxy-Secret "replace-with-the-proxy-secret";

    proxy_pass http://slop:8000;
}
```

In a real Nginx deployment, keep the `auth_request` location internal as
appropriate for the official outpost template, store the secret outside the
site file where your secret-management setup supports it, and explicitly
clear client-supplied `X-authentik-*` and `X-Slop-Auth-Proxy-Secret` headers
before the trusted values are set. Do not publish Slop's port 8000 directly.

### Traefik pattern

Use Authentik's forward-auth middleware and copy only the identity response
headers needed by Slop. Add the Slop secret with a trusted file-provider or
secret-backed middleware; do not accept it from the incoming request:

```yaml
http:
  middlewares:
    slop-auth:
      forwardAuth:
        address: http://authentik_outpost:9000/outpost.goauthentik.io/auth
        trustForwardHeader: true
        authResponseHeaders:
          - X-authentik-uid
          - X-authentik-username
          - X-authentik-meta-app
    slop-auth-secret:
      headers:
        customRequestHeaders:
          X-Slop-Auth-Proxy-Secret: replace-with-the-proxy-secret
```

Apply both middlewares to the Slop router, clear incoming copies before the
trusted middleware chain, and route the outpost asset path to the outpost as
shown in Authentik's current Traefik template. Keep Slop's Docker port on the
private network.

### Caddy pattern

Use Authentik's Caddy forward-auth template, then copy the three identity
headers and inject the shared secret on the upstream request:

```caddy
slop.example.com {
    forward_auth authentik_outpost:9000 {
        uri /outpost.goauthentik.io/auth
        copy_headers X-authentik-uid X-authentik-username X-authentik-meta-app
    }

    reverse_proxy slop:8000 {
        header_up X-Slop-Auth-Proxy-Secret replace-with-the-proxy-secret
    }
}
```

Adapt the placeholder header variables to the exact Authentik template for
your Caddy version. The client must never be able to choose these headers, and
`/outpost.goauthentik.io/*` must be routed to the outpost when the selected
template requires it.

Use an Authentik release containing the forward-auth malformed-cookie fix; for
the release lines called out in Authentik's advisory, use at least 2025.10.4 or
2025.12.4. See [Authentik's CVE-2026-25748 advisory](https://docs.goauthentik.io/security/cves/CVE-2026-25748/).

## Native OIDC mode

Create a confidential OAuth2/OIDC Provider and application in Authentik. Set
the redirect URI exactly to:

```text
https://slop.example.com/api/v1/auth/oidc/callback
```

Configure Authentik's back-channel logout URI as:

```text
https://slop.example.com/api/v1/auth/oidc/backchannel-logout
```

Then set:

```dotenv
AUTH_MODE=authentik_oidc
PUBLIC_URL=https://slop.example.com
AUTHENTIK_OIDC_DISCOVERY_URL=https://auth.example.com/application/o/slop/.well-known/openid-configuration
AUTHENTIK_OIDC_CLIENT_ID=<client-id>
AUTHENTIK_OIDC_CLIENT_SECRET=<client-secret>
```

Slop uses fixed `openid profile email` scopes, authorization-code exchange,
confidential-client authentication, PKCE S256, encrypted five-minute state
cookies, nonce checking, discovery/JWKS caching with one rotation refresh,
UserInfo only when `preferred_username` is absent, and bounded provider
timeouts. Access and refresh tokens are discarded after callback; only the
encrypted ID-token hint and provider session ID needed for logout are retained
with the local session.

The OIDC sign-in screen has one explicit Authentik button. The post-logout page
does not automatically start another sign-in. Local logout deletes the Slop
session before redirecting to Authentik's discovered end-session endpoint.

## Verification and troubleshooting

After restarting, check the public mode without exposing secrets:

```sh
curl -fsS https://slop.example.com/api/v1/auth/config
curl -fsS https://slop.example.com/api/v1/health/ready
```

Test all of the following in a private browser session:

- one prepared user can sign in and reaches the requested page;
- an unknown Authentik username is denied without a new Slop account;
- owner-only actions still use the local Slop role;
- logout clears the local session and reaches Authentik sign-out;
- disabling or revoking the OIDC session is reflected by back-channel logout.

Useful error codes include `AUTHENTIK_UNKNOWN_ACCOUNT`,
`AUTHENTIK_ACCOUNT_DISABLED`, `AUTHENTIK_AMBIGUOUS_ACCOUNT`,
`AUTHENTIK_IDENTITY_CONFLICT`, `AUTHENTIK_PROXY_HEADERS_REQUIRED`,
`AUTHENTIK_PROVIDER_UNAVAILABLE`, and `AUTHENTIK_INVALID_CALLBACK`.

If the configuration is invalid, the container fails closed during startup.
If all external users are denied, temporarily switch back to `builtin`, restart,
repair the matching local usernames or provider configuration, and switch back
after testing. Never work around an error by exposing port 8000 directly or by
trusting client-provided Authentik headers.

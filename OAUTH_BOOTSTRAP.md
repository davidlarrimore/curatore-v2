# Local OAuth Development Server — Bootstrap Guide

## Purpose

This document defines the requirements and setup for a **standalone, reusable mock OAuth server** for local development. The server runs independently of any consuming project and provides a standards-compliant OAuth 2.1 / OpenID Connect identity provider on `localhost`.

Any project that needs OAuth in development (Curatore, MCP gateways, APIs, SPAs) points its OAuth configuration at this server instead of a cloud IdP like Microsoft Entra ID.

## Why a Separate Repo?

- **Reusable** — One mock IdP serves all your local projects
- **Decoupled** — No auth infrastructure polluting individual project docker-compose files
- **Consistent** — Same test users, scopes, and claims across all projects
- **Optional** — Projects that don't need auth locally just don't point at it

## Architecture

```
┌──────────────────────────────────────────────────┐
│              local-oauth-dev (this repo)          │
│                                                   │
│  mock-oauth2-server  ──  port 9980               │
│  ├── /.well-known/openid-configuration            │
│  ├── /authorize  (interactive login page)         │
│  ├── /token      (token exchange)                 │
│  └── /jwks       (public signing keys)            │
└──────────────────────────────────────────────────┘
        ▲               ▲               ▲
        │               │               │
   Project A       Project B       Project C
   (Curatore)      (other app)     (other app)
   OAUTH_ISSUER=   OAUTH_ISSUER=   OAUTH_ISSUER=
   http://localhost http://localhost http://localhost
   :9980/default   :9980/default   :9980/default
```

Port 9980 is chosen to avoid conflicts with common dev ports (3000, 8000, 8080, 9000, etc.).

## Recommended Implementation

### Option A: mock-oauth2-server (Recommended)

[mock-oauth2-server](https://github.com/navikt/mock-oauth2-server) by NAV (Norwegian Labour and Welfare Administration). Single Docker image, minimal config, auto-generates signing keys, issues real signed JWTs.

### Option B: Keycloak

Heavier (~512MB RAM, Java startup time) but more realistic. Better for testing consent screens, realm isolation, and advanced OIDC flows.

This document assumes **Option A** for its examples. The consuming project doesn't care which one you use — it just needs a standard OIDC discovery endpoint.

## Repo Structure

```
local-oauth-dev/
├── docker-compose.yml          # Mock OAuth server
├── config/
│   └── oauth-config.json       # Users, scopes, claim mappings
├── scripts/
│   └── get-test-token.sh       # Helper to get a token for curl/Postman testing
├── .env.example                # Default port, issuer config
└── README.md                   # Usage instructions
```

## docker-compose.yml

```yaml
services:
  mock-oauth:
    image: ghcr.io/navikt/mock-oauth2-server:2.1.10
    container_name: local-oauth-dev
    ports:
      - "${OAUTH_PORT:-9980}:9980"
    environment:
      SERVER_PORT: 9980
      JSON_CONFIG_PATH: /config/oauth-config.json
    volumes:
      - ./config/oauth-config.json:/config/oauth-config.json:ro
    restart: unless-stopped
```

## config/oauth-config.json

This configures the mock server to simulate Microsoft Entra ID-like tokens with the claims that consuming projects expect.

```json
{
  "interactiveLogin": true,
  "httpServer": "NettyWrapper",
  "tokenCallbacks": [
    {
      "issuerId": "default",
      "tokenExpiry": 3600,
      "requestMappings": [
        {
          "requestParam": "scope",
          "match": "*",
          "claims": {
            "aud": ["curatore"],
            "iss": "http://localhost:9980/default",
            "sub": "${claims.sub}",
            "email": "${claims.email}",
            "name": "${claims.name}",
            "preferred_username": "${claims.email}",
            "oid": "${claims.sub}",
            "tid": "local-dev-tenant",
            "roles": ["user"],
            "scp": "mcp:tools openid profile email"
          }
        }
      ]
    }
  ]
}
```

### Key Claims (Entra ID Compatibility)

| Claim | Purpose | Entra ID Equivalent |
|-------|---------|---------------------|
| `sub` | Unique user identifier | User Object ID |
| `email` | User's email address | `email` or `upn` |
| `name` | Display name | `name` |
| `preferred_username` | Login identifier | `preferred_username` |
| `oid` | Object ID (mapped to sub) | `oid` |
| `tid` | Tenant ID | `tid` |
| `aud` | Audience (your app) | App ID URI |
| `scp` | Scopes granted | `scp` |
| `roles` | App roles | `roles` |

## scripts/get-test-token.sh

Helper script for getting a token without a browser (useful for curl/Postman/CLI testing):

```bash
#!/usr/bin/env bash
# Fetches a test token from the mock OAuth server using client_credentials grant.
# Usage: ./scripts/get-test-token.sh [email]

OAUTH_BASE="${OAUTH_BASE:-http://localhost:9980/default}"
EMAIL="${1:-dev@example.com}"

TOKEN=$(curl -s -X POST "${OAUTH_BASE}/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials" \
  -d "client_id=test-client" \
  -d "client_secret=test-secret" \
  -d "scope=openid profile email mcp:tools" \
  | jq -r '.access_token')

echo "Access Token:"
echo "$TOKEN"
echo ""
echo "Decoded payload:"
echo "$TOKEN" | cut -d'.' -f2 | base64 -d 2>/dev/null | jq .
```

## .env.example

```bash
# Port for the mock OAuth server (default: 9980)
OAUTH_PORT=9980
```

## OIDC Discovery Endpoints

Once running, the server exposes standard OIDC endpoints:

| Endpoint | URL |
|----------|-----|
| Discovery | `http://localhost:9980/default/.well-known/openid-configuration` |
| Authorization | `http://localhost:9980/default/authorize` |
| Token | `http://localhost:9980/default/token` |
| JWKS | `http://localhost:9980/default/jwks` |
| Userinfo | `http://localhost:9980/default/userinfo` |

The `default` path segment is the "issuer ID" — you can create multiple issuers if needed.

## How Consuming Projects Use This

### Step 1: Start the mock server

```bash
cd local-oauth-dev
docker compose up -d
```

### Step 2: Configure your project

In your project's `.env` or environment config:

```bash
# OAuth / OIDC Configuration
OAUTH_ISSUER_URL=http://localhost:9980/default
OAUTH_AUDIENCE=curatore
OAUTH_JWKS_URI=http://localhost:9980/default/jwks

# Disable if you want to skip auth entirely for quick iteration
ENABLE_AUTH=true
```

### Step 3: Validate tokens in your app

Your application fetches the JWKS from the mock server and validates JWTs the same way it would validate Entra ID tokens. The only config difference between dev and production is the issuer URL and audience:

| Setting | Local Dev | Production |
|---------|-----------|------------|
| `OAUTH_ISSUER_URL` | `http://localhost:9980/default` | `https://login.microsoftonline.com/{tenant}/v2.0` |
| `OAUTH_AUDIENCE` | `curatore` | Your Entra ID App Registration client ID |
| `OAUTH_JWKS_URI` | `http://localhost:9980/default/jwks` | `https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys` |

### Step 4: Interactive login (browser-based flows)

When your app redirects to the mock server's `/authorize` endpoint, it shows a simple login form where you can type any username/email. No real credentials needed — it accepts anything and issues a token with those claims. This simulates the Entra ID browser login redirect.

## Test Users

The mock server accepts any credentials at the interactive login page. For consistency across projects, use these conventions:

| User | Email | Role | Purpose |
|------|-------|------|---------|
| Dev Admin | `admin@example.com` | admin | Full access testing |
| Dev User | `user@example.com` | user | Standard user testing |
| Dev Readonly | `readonly@example.com` | viewer | Read-only testing |

These aren't pre-configured accounts — you simply type these values at the login page and the server issues tokens with matching claims.

## Relationship to Production Auth (Microsoft Entra ID)

This mock server is **not** a replacement for Entra ID testing. It's for daily development velocity. The recommended testing progression:

| Stage | Auth Provider | Purpose |
|-------|--------------|---------|
| **Daily dev** | Mock OAuth server (this repo) | Fast iteration, no internet needed |
| **Auth integration testing** | [Free Entra ID dev tenant](https://learn.microsoft.com/en-us/entra/verified-id/how-to-create-a-free-developer-account) | Real Entra ID behavior, consent flows |
| **Staging / Pre-prod** | Entra ID staging tenant | Production-like environment |
| **Production** | Entra ID production tenant | Real users, real policies |

## Open WebUI Integration

When testing Open WebUI → MCP server OAuth flows locally:

1. Start the mock OAuth server
2. Configure Open WebUI's MCP connection with auth type **OAuth 2.1**
3. Set the MCP server URL to your local MCP gateway
4. The MCP gateway's Protected Resource Metadata points to the mock server
5. Open WebUI triggers the OAuth flow → mock server login page → token issued → per-user identity flows through

This simulates the production flow where Open WebUI would use Entra ID.

## References

- [mock-oauth2-server GitHub](https://github.com/navikt/mock-oauth2-server)
- [MCP Authorization Spec](https://modelcontextprotocol.io/docs/tutorials/security/authorization)
- [Microsoft Entra ID Dev Tenant](https://learn.microsoft.com/en-us/entra/verified-id/how-to-create-a-free-developer-account)
- [OAuth 2.1 Spec](https://datatracker.ietf.org/doc/html/draft-ietf-oauth-v2-1-13)
- [RFC 9728 — Protected Resource Metadata](https://datatracker.ietf.org/doc/html/rfc9728)

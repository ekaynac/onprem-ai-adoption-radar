# Security Policy

## Supported versions

The project is pre-1.0; only the latest `main` branch receives security fixes.
Pin a commit hash if you deploy it.

## Reporting a vulnerability

Please open a private GitHub security advisory
(**Security → Report a vulnerability** on the repository) rather than a public
issue. You can also reach the maintainer via the contact listed on the GitHub
profile. Expect an initial response within 7 days.

## Security model

This project is designed to run **locally or on a trusted internal network**.
Its network posture:

- **Reads are public by design.** The radar publishes a static site and an API
  whose GET endpoints are always readable — that is the product.
- **Writes are opt-in protected.** Set `RADAR_API_TOKEN` to require a
  `Authorization: Bearer <token>` header (compared with a constant-time
  function) for:
  - all mutating API endpoints (`POST/PUT/DELETE /api/v1/...`),
  - the dashboard seed form (`POST /sources`).
- **CSRF:** cross-origin submissions to `POST /sources` are rejected by Origin
  checking regardless of token state.
- The API is **open when `RADAR_API_TOKEN` is unset** — appropriate for local
  development, *not* for exposure beyond localhost without a reverse proxy,
  network ACLs, or the token set.

If you expose either app beyond localhost, set `RADAR_API_TOKEN` and front it
with TLS.

## Data handling

- The pipeline fetches operator-configured feeds (RSS/GitHub/HuggingFace) and
  sends selected text to Anthropic's API for news classification only when
  configured with `ANTHROPIC_API_KEY`. Nothing user-supplied is fetched.
- Webhooks sign payloads with HMAC-SHA256 (`RADAR_WEBHOOK_SECRET`).

## Known limitations

- No rate limiting or brute-force lockout on token-protected endpoints;
  rely on your reverse proxy for this.
- GET endpoints cannot be locked down per-token today.

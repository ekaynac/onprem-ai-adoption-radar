"""Application constants."""

APP_NAME = "onprem-ai-adoption-radar"
DEFAULT_DATA_DIR = "data"

# RSS/Atom feeds behind bot-protection (e.g. Cloudflare) serve a challenge page
# to requests with no/obvious-bot User-Agent, which feedparser then parses to
# zero entries. A browser-like UA that still identifies the project honestly
# gets the real feed back.
RSS_USER_AGENT = (
    "Mozilla/5.0 (compatible; onprem-ai-adoption-radar/1.0; "
    "+https://www.megabilgisayar.com.tr)"
)
RSS_ACCEPT = (
    "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8"
)

# A scan whose source error-rate reaches this fraction is a collection outage:
# it is recorded (raw signals + meta) but never scored — scoring near-empty
# input produces artificial ring churn (see 2026-07-27 hardening spec).
DEGRADED_SOURCE_ERROR_THRESHOLD = 0.5

# Single source of truth for the catalog's "fresh" freshness window. The API
# computes freshness from it, and the published public snapshot carries it as
# `freshness_window_days` so the static-edition SPA never hardcodes its own
# copy (see frontend/src/api/client.ts).
CATALOG_FRESHNESS_WINDOW_DAYS = 7

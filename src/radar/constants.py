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

export function IntegrationsPage() {
  const mcpConfig = `{
  "mcpServers": {
    "onprem-intelligence": {
      "command": "uv",
      "args": ["run", "radar", "mcp"]
    }
  }
}`;
  return (
    <section className="page-stack">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Integrate · Delivery surfaces</p>
          <h1>One intelligence contract, every transport</h1>
          <p className="lede">REST, MCP, feeds, signed webhooks, and static export share canonical IDs.</p>
        </div>
      </header>
      <div className="integration-grid">
        <article className="panel">
          <p className="eyebrow">REST & OpenAPI</p>
          <h2>Versioned API</h2>
          <a href="/api/docs">Interactive documentation</a>
          <a href="/api/v1/openapi.json">OpenAPI schema</a>
        </article>
        <article className="panel">
          <p className="eyebrow">Feeds</p>
          <h2>Public release channels</h2>
          <a href="/api/v1/integrations/feed.atom">Atom</a>
          <a href="/api/v1/integrations/feed.rss">RSS</a>
          <a href="/api/v1/integrations/feed.json">JSON Feed</a>
        </article>
        <article className="panel">
          <p className="eyebrow">Static edition</p>
          <h2>Read-only snapshot</h2>
          <a href="/api/v1/integrations/public-snapshot">public-snapshot.v1.json</a>
          <span>Workspace fields are structurally excluded.</span>
        </article>
      </div>
      <section className="panel">
        <p className="eyebrow">MCP server</p>
        <h2>Connect an architecture agent</h2>
        <pre className="record-view" tabIndex={0}>{mcpConfig}</pre>
      </section>
      <section className="panel">
        <p className="eyebrow">Signed webhooks</p>
        <h2>Durable delivery with bounded retry</h2>
        <p className="claim-reason">HMAC-SHA256 · 1, 5, 30, 120, and 600 minute retry windows.</p>
      </section>
    </section>
  );
}

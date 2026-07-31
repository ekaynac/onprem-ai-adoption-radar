type DeliveryLink = {
  href: string;
  label: string;
  format: string;
  purpose: string;
};

const histories: DeliveryLink[] = [
  {
    href: "history.jsonl",
    label: "Project history",
    format: "JSONL",
    purpose: "Append-only ring and project changes.",
  },
  {
    href: "model-history.jsonl",
    label: "Model history",
    format: "JSONL",
    purpose: "Model recommendation and ring transitions.",
  },
  {
    href: "technique-history.jsonl",
    label: "Technique history",
    format: "JSONL",
    purpose: "Research technique recommendation changes.",
  },
  {
    href: "trending-observations.jsonl",
    label: "Trending observations",
    format: "JSONL",
    purpose: "Raw repository momentum observations.",
  },
];

const feeds: DeliveryLink[] = [
  {
    href: "changes.rss",
    label: "Unified changes · RSS",
    format: "RSS 2.0",
    purpose: "Project and intelligence changes for feed readers.",
  },
  {
    href: "changes.json",
    label: "Unified changes · JSON Feed",
    format: "JSON Feed 1.1",
    purpose: "Machine-readable unified change stream.",
  },
  {
    href: "changes.xml",
    label: "Unified changes · Atom",
    format: "Atom",
    purpose: "Project and intelligence changes for Atom subscribers.",
  },
  {
    href: "changes-models.xml",
    label: "Model changes · Atom",
    format: "Atom",
    purpose: "Model-only recommendation changes.",
  },
  {
    href: "changes-research.xml",
    label: "Research changes · Atom",
    format: "Atom",
    purpose: "Research technique changes.",
  },
  {
    href: "digests/digest.xml",
    label: "Weekly digest · Atom",
    format: "Atom",
    purpose: "Weekly architecture intelligence digest.",
  },
  {
    href: "digests/digest-rss.xml",
    label: "Weekly digest · RSS",
    format: "RSS 2.0",
    purpose: "Weekly digest for RSS readers.",
  },
];

function DeliveryList({ items }: { items: DeliveryLink[] }) {
  return (
    <ul className="delivery-list">
      {items.map((item) => (
        <li key={item.href}>
          <a href={item.href}>{item.label}</a>
          <span>{item.format}</span>
          <p>{item.purpose}</p>
        </li>
      ))}
    </ul>
  );
}

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
          <p className="eyebrow">Integrate · Durable delivery surfaces</p>
          <h1>Take the radar with you</h1>
          <p className="lede">
            Download the append-only evidence trail, subscribe to public changes,
            or connect an architecture agent to the same intelligence contract.
          </p>
        </div>
      </header>

      <div className="integration-grid">
        <article className="panel">
          <p className="eyebrow">History</p>
          <h2>Durable evidence logs</h2>
          <DeliveryList items={histories} />
        </article>
        <article className="panel integration-feed-panel">
          <p className="eyebrow">Feeds</p>
          <h2>Public subscription channels</h2>
          <DeliveryList items={feeds} />
        </article>
        <article className="panel">
          <p className="eyebrow">REST & OpenAPI</p>
          <h2>Versioned API</h2>
          <ul className="delivery-list">
            <li>
              <a href="/api/docs">Interactive API documentation</a>
              <span>Swagger UI</span>
              <p>Explore the live command-center API.</p>
            </li>
            <li>
              <a href="/api/v1/openapi.json">OpenAPI schema</a>
              <span>OpenAPI 3</span>
              <p>Generate typed clients and validate integrations.</p>
            </li>
            <li>
              <a href="data/public-snapshot.v1.json">Public snapshot</a>
              <span>JSON</span>
              <p>Static, workspace-free projection used by this site.</p>
            </li>
          </ul>
        </article>
      </div>

      <section className="panel">
        <p className="eyebrow">MCP server</p>
        <h2>Connect an architecture agent</h2>
        <p className="claim-reason">
          Run <code>uv run radar mcp</code> from the repository, then add this
          local server configuration to your MCP client.
        </p>
        <pre className="record-view" tabIndex={0}>{mcpConfig}</pre>
      </section>
    </section>
  );
}

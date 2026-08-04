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

type McpTool = {
  name: string;
  signature: string;
  answer: string;
};

const flagshipTools: McpTool[] = [
  {
    name: "recommend",
    signature: "recommend(task, device, allowed_licenses?, min_context?)",
    answer:
      "What should I run? Ranked candidates with capacity fit, task percentile, license gate, ring, and reasons — exclusions come back with reasons too.",
  },
  {
    name: "whats_new",
    signature:
      "whats_new(engines?, models_in_production?, quant_formats?, devices?)",
    answer:
      "What changed that touches THIS stack? Act/Evaluate alerts with receipts, diffed from classified news and ring moves. Silence for everything else.",
  },
  {
    name: "benchmarks",
    signature: "benchmarks(model_id)",
    answer:
      "Triangulated benchmark table: every source's score with URL, independent consensus, self-reported gaps flagged, percentile among tracked models.",
  },
  {
    name: "plan_capacity",
    signature:
      "plan_capacity(model_id, device, concurrent_requests, avg_context_tokens, ...)",
    answer:
      "GPU count, memory budget, and throughput estimate for a target workload on a device.",
  },
  {
    name: "can_run",
    signature: "can_run(model_id, device, context_tokens?)",
    answer:
      "Does it fit? Verdict + best quant for a device preset or custom spec.",
  },
  {
    name: "search_intelligence",
    signature: "search_intelligence(query)",
    answer:
      "Significance-ranked search across the whole tracked catalog — models, projects, techniques.",
  },
];

export function IntegrationsPage({ staticMode = false }: { staticMode?: boolean }) {
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
          <p className="eyebrow">Integrate · MCP & API</p>
          <h1>Plug Mega's radar into your assistant</h1>
          <p className="lede">
            The Intelligence Desk is a product surface, not just a site:
            every answer, alert, and benchmark table on these pages is an
            MCP tool your agent can call — same engines, same citations,
            inside your workflow.
          </p>
        </div>
      </header>

      <section className="panel" aria-labelledby="mcp-title">
        <p className="eyebrow">MCP server</p>
        <h2 id="mcp-title">Two lines to connect</h2>
        <p className="claim-reason">
          Run <code>uv run radar mcp</code> from the repository, then add
          this server to your MCP client (Claude Desktop, Claude Code, or
          any MCP-capable agent).
        </p>
        <pre className="record-view" tabIndex={0}>{mcpConfig}</pre>
        <div className="release-table-wrap">
          <table className="release-table">
            <thead>
              <tr>
                <th>Tool</th>
                <th>The question it answers</th>
              </tr>
            </thead>
            <tbody>
              {flagshipTools.map((tool) => (
                <tr key={tool.name}>
                  <td>
                    <strong>{tool.name}</strong>
                    <br />
                    <code>{tool.signature}</code>
                  </td>
                  <td>{tool.answer}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="claim-meta">
          Plus 30+ further tools: catalog queries, device fit reports,
          platform support matrices, technique radar, trending, source
          health, and workspace-aware search.
        </p>
      </section>

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
            {!staticMode && (
              <>
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
              </>
            )}
            <li>
              <a href="data/public-snapshot.v1.json">Public snapshot</a>
              <span>JSON</span>
              <p>Static, workspace-free projection used by this site.</p>
            </li>
          </ul>
          {staticMode && (
            <p className="claim-reason">
              Start the live command center with <code>uv run radar serve</code> to
              use Swagger UI and the versioned REST API.
            </p>
          )}
        </article>
      </div>

    </section>
  );
}

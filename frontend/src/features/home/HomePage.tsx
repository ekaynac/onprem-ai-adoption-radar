import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { usePublicSnapshot } from "../catalog/catalogQueries";


const VERDICT_LABELS: Record<string, string> = {
  act: "Act",
  evaluate: "Evaluate",
  ignore: "Ignore",
};


export function HomePage() {
  const snapshot = usePublicSnapshot(true);
  const navigate = useNavigate();
  const advisor = snapshot.data?.advisor ?? null;
  const desk = snapshot.data?.desk ?? null;
  const demo = snapshot.data?.stack_demo ?? null;
  const newsroom = snapshot.data?.newsroom ?? null;
  const [task, setTask] = useState("coding");
  const [device, setDevice] = useState("");

  if (snapshot.isLoading) {
    return (
      <div className="loading-grid" aria-label="Loading home">
        <span />
        <span />
      </div>
    );
  }

  const briefItems = (desk?.brief?.items ?? [])
    .filter((item) => item.verdict !== "ignore")
    .slice(0, 4);
  const track = desk?.track_record ?? null;

  return (
    <section className="page-stack" aria-labelledby="home-title">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Mega · On-Prem Intelligence Desk</p>
          <h1 id="home-title">What should you run?</h1>
          <p className="lede">
            Task and hardware in — a ranked, fully cited recommendation
            out: capacity fit, triangulated benchmarks, license gate,
            ring, and cost. Derived from public evidence, never vibes.
          </p>
        </div>
        {track && (
          <div className="freshness-stamp" aria-label="Public track record">
            Calls kept score: {track.confirmed}✓ / {track.wrong}✗ ·{" "}
            {track.open} open
            {track.hit_rate_pct != null && ` · ${track.hit_rate_pct}% hit rate`}
          </div>
        )}
      </header>

      <section className="panel" aria-labelledby="ask-title">
        <p className="eyebrow">The Answer Machine</p>
        <h2 id="ask-title">Ask the question every architect starts with</h2>
        <div className="filter-bar" aria-label="Answer Machine inputs">
          <label>
            <span>Task</span>
            <select
              value={task}
              onChange={(event) => setTask(event.target.value)}
            >
              {Object.entries(
                advisor?.tasks ?? { coding: { label: "Coding assistant" } },
              ).map(([value, spec]) => (
                <option value={value} key={value}>
                  {spec.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Hardware</span>
            <select
              value={device}
              onChange={(event) => setDevice(event.target.value)}
            >
              <option value="">Select device</option>
              {(advisor?.devices ?? []).map((id) => (
                <option value={id} key={id}>
                  {id}
                </option>
              ))}
            </select>
          </label>
          <button
            className="primary-button"
            disabled={!device}
            type="button"
            onClick={() =>
              navigate(
                `/advisor?task=${encodeURIComponent(task)}&device=${encodeURIComponent(device)}`,
              )
            }
          >
            Get the answer
          </button>
        </div>
        <p className="claim-meta">
          Every component of the answer cites its source — the same engine
          serves the <Link to="/integrations">MCP tools</Link> your
          assistant can call.
        </p>
      </section>

      <div className="workspace-grid">
        <section className="panel" aria-labelledby="home-desk-title">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">The Desk — this week</p>
              <h2 id="home-desk-title">
                {desk?.brief?.id ?? "Weekly brief"}
              </h2>
            </div>
            <Link className="text-button" to="/desk">
              Full brief →
            </Link>
          </div>
          {briefItems.length === 0 ? (
            <div className="empty-state">
              <strong>No brief published yet</strong>
              <span>The first weekly brief lands with the next cycle.</span>
            </div>
          ) : (
            <ul className="brief-list">
              {briefItems.map((item) => (
                <li key={item.id}>
                  <div className="brief-item-head">
                    <strong>{item.subject}</strong>
                    <span className={`verdict-pill verdict-${item.verdict}`}>
                      {VERDICT_LABELS[item.verdict]}
                    </span>
                  </div>
                  <p className="claim-reason">{item.what_happened}</p>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="panel" aria-labelledby="home-alerts-title">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Stack alerts</p>
              <h2 id="home-alerts-title">Silence unless it touches you</h2>
            </div>
            <Link className="text-button" to="/workspaces">
              Stack profile →
            </Link>
          </div>
          <p className="claim-reason">
            Classified news and ring moves are diffed against a stack
            profile — the demo reference stack currently shows{" "}
            {demo?.alerts.counts.act ?? 0} act and{" "}
            {demo?.alerts.counts.evaluate ?? 0} evaluate alert(s).
          </p>
          {newsroom && (
            <p className="claim-meta">
              Newsroom: {newsroom.counts.classified} classified item(s) ·{" "}
              {newsroom.counts.breaking} breaking ·{" "}
              <Link to="/newsroom">browse →</Link>
            </p>
          )}
        </section>
      </div>

      <section className="panel" aria-labelledby="home-mcp-title">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">MCP & API — the product</p>
            <h2 id="home-mcp-title">Plug Mega's radar into your assistant</h2>
          </div>
          <Link className="text-button" to="/integrations">
            Setup & tools →
          </Link>
        </div>
        <p className="claim-reason">
          <code>recommend</code>, <code>whats_new</code>,{" "}
          <code>benchmarks</code>, <code>plan_capacity</code> and 30+ more
          tools expose this intelligence to any MCP client — the same
          cited answers, in your workflow.
        </p>
      </section>

      <p className="data-timestamp">
        Evidence appendix: <Link to="/catalog">catalog</Link> ·{" "}
        <Link to="/releases">release stream</Link> ·{" "}
        <Link to="/trending">trending</Link> ·{" "}
        <Link to="/overview">rings overview</Link> — every answer above
        links down into them.
      </p>
    </section>
  );
}

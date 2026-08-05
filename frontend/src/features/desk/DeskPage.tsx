import { Link } from "react-router-dom";

import { usePublicSnapshot } from "../catalog/catalogQueries";
import { profileTerms, textTouchesProfile } from "../workspaces/stackMatch";
import { useWorkspaces } from "../workspaces/WorkspaceSwitcher";
import { useActiveWorkspaceId } from "../workspaces/workspaceStore";


const SECTION_LABELS: Record<string, string> = {
  "ring-moves": "Ring moves",
  "benchmark-moves": "Benchmark moves",
  "new-repos": "New repositories",
  news: "Breaking news",
  hardware: "New platforms",
};

const VERDICT_LABELS: Record<string, string> = {
  act: "Act",
  evaluate: "Evaluate",
  ignore: "Ignore",
};


export function DeskPage({
  staticMode = import.meta.env.MODE === "static",
}: {
  staticMode?: boolean;
}) {
  const snapshot = usePublicSnapshot(true);
  const desk = snapshot.data?.desk ?? null;
  const brief = desk?.brief ?? null;
  const workspaces = useWorkspaces(!staticMode);
  const activeWorkspaceId = useActiveWorkspaceId();

  if (snapshot.isLoading) {
    return <div className="loading-grid" aria-label="Loading desk"><span /><span /></div>;
  }

  // Personalization: the active workspace's stack wins; the public demo
  // profile demonstrates the mechanism in static mode.
  const workspaceList = Array.isArray(workspaces.data)
    ? workspaces.data
    : [];
  const activeWorkspace = workspaceList.find(
    (workspace) => workspace.id === activeWorkspaceId,
  );
  const profile = activeWorkspace
    ? { devices: activeWorkspace.devices, stack: activeWorkspace.stack }
    : (snapshot.data?.stack_demo?.profile ?? null);
  const terms = profile ? profileTerms(profile) : [];
  const touches = (item: {
    subject: string;
    what_happened: string;
    rationale: string;
  }) =>
    terms.length > 0 &&
    textTouchesProfile(
      `${item.subject} ${item.what_happened} ${item.rationale}`,
      terms,
    );

  const sections = new Map<string, typeof brief extends null ? never : NonNullable<typeof brief>["items"]>();
  for (const item of brief?.items ?? []) {
    const bucket = sections.get(item.section) ?? [];
    bucket.push(item);
    sections.set(item.section, bucket);
  }
  // Profile-affecting items float to the top of each section.
  for (const bucket of sections.values()) {
    bucket.sort((a, b) => Number(touches(b)) - Number(touches(a)));
  }

  return (
    <section className="page-stack" aria-labelledby="desk-title">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Intelligence · The Desk</p>
          <h1 id="desk-title">This week, with verdicts</h1>
          <p className="lede">
            What happened, what it means for on-prem operators, and a
            falsifiable call — scored publicly over time.
          </p>
        </div>
        {desk?.track_record && (
          <div className="freshness-stamp" aria-label="Track record">
            {desk.track_record.confirmed}✓ / {desk.track_record.wrong}✗ ·{" "}
            {desk.track_record.open} open
            {desk.track_record.hit_rate_pct != null &&
              ` · ${desk.track_record.hit_rate_pct}% hit rate`}
          </div>
        )}
      </header>

      {!brief ? (
        <div className="empty-state">
          <strong>No brief published yet</strong>
          <span>The first weekly brief lands with the next publish cycle.</span>
        </div>
      ) : (
        <>
          <p className="claim-meta">
            {brief.id} · {brief.items.length} item(s) — act{" "}
            {brief.verdict_counts.act ?? 0}, evaluate{" "}
            {brief.verdict_counts.evaluate ?? 0}, ignore{" "}
            {brief.verdict_counts.ignore ?? 0} · {brief.verdict_rules}
          </p>
          {brief.spotlight && (
            <section className="panel">
              <p className="eyebrow">Spotlight — this week's worked answer</p>
              <h2>
                {brief.spotlight.task_label} on {brief.spotlight.device} →{" "}
                <Link
                  to={`/advisor?task=${encodeURIComponent(brief.spotlight.task)}&device=${encodeURIComponent(brief.spotlight.device)}`}
                >
                  {brief.spotlight.top_candidate.name}
                </Link>
              </h2>
              <ul className="try-evidence">
                {brief.spotlight.top_candidate.reasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            </section>
          )}
          {[...sections.entries()].map(([section, items]) => (
            <section className="panel" key={section}>
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">{SECTION_LABELS[section] ?? section}</p>
                </div>
              </div>
              <ul className="brief-list">
                {items.map((item) => (
                  <li key={item.id}>
                    <div className="brief-item-head">
                      <strong>
                        {item.subject}
                        {touches(item) && (
                          <span className="stack-badge">Your stack</span>
                        )}
                      </strong>
                      <span className={`verdict-pill verdict-${item.verdict}`}>
                        {VERDICT_LABELS[item.verdict]}
                      </span>
                    </div>
                    <p>{item.what_happened}</p>
                    <p className="claim-reason">{item.why_it_matters}</p>
                    <p className="claim-meta">
                      {item.rationale}
                      {item.receipts.map((receipt) =>
                        receipt.startsWith("http") ? (
                          <a
                            href={receipt}
                            key={receipt}
                            rel="noreferrer"
                            target="_blank"
                          >
                            {" "}
                            receipt ↗
                          </a>
                        ) : (
                          <span key={receipt}> · {receipt}</span>
                        ),
                      )}
                    </p>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </>
      )}

      {(desk?.calls.length ?? 0) > 0 && (
        <section className="panel" aria-labelledby="calls-title">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Calls ledger</p>
              <h2 id="calls-title">Every call, kept score</h2>
            </div>
          </div>
          <div className="release-table-wrap">
            <table className="release-table">
              <thead>
                <tr>
                  <th>Subject</th>
                  <th>Verdict</th>
                  <th>Status</th>
                  <th>Made</th>
                  <th>Note</th>
                </tr>
              </thead>
              <tbody>
                {desk?.calls.map((call) => (
                  <tr key={call.call_id}>
                    <td>{call.subject}</td>
                    <td>
                      <span className={`verdict-pill verdict-${call.verdict}`}>
                        {VERDICT_LABELS[call.verdict] ?? call.verdict}
                      </span>
                    </td>
                    <td>{call.status}</td>
                    <td>{new Date(call.made_at).toLocaleDateString()}</td>
                    <td>{call.note ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </section>
  );
}

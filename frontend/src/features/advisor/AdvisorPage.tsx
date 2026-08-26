import { useMemo, useState } from "react";

import { useWorkspaces } from "../workspaces/WorkspaceSwitcher";
import { useActiveWorkspaceId } from "../workspaces/workspaceStore";
import { Link, useSearchParams } from "react-router-dom";

import { apiFetch } from "../../api/client";
import { formatContext, formatParams } from "../catalog/format";
import {
  usePublicSnapshot,
  type AdvisorAnswer,
  type AdvisorCandidate,
} from "../catalog/catalogQueries";


const CONTEXT_CHOICES = [
  { value: "", label: "Any context" },
  { value: "32768", label: "≥ 32K tokens" },
  { value: "131072", label: "≥ 128K tokens" },
];

function candidatePassesPolicy(
  candidate: AdvisorCandidate,
  license: string,
  minContext: number | null,
): string | null {
  if (license && candidate.license.value !== license) {
    return `License ${candidate.license.value ?? "unknown"} does not match policy ${license}`;
  }
  if (
    minContext != null &&
    candidate.context_length != null &&
    candidate.context_length < minContext
  ) {
    return `Context ${candidate.context_length} below required ${minContext}`;
  }
  return null;
}

export function AdvisorPage({ staticMode = false }: { staticMode?: boolean }) {
  const snapshot = usePublicSnapshot(true);
  const advisor = snapshot.data?.advisor ?? null;
  const [params, setParams] = useSearchParams();
  const workspaces = useWorkspaces(!staticMode);
  const activeWorkspaceId = useActiveWorkspaceId();
  const task = params.get("task") ?? "coding";
  // The Answer Machine defaults to the profile's hardware: the active
  // workspace's first preset device, else the public demo profile's.
  const workspaceList = Array.isArray(workspaces.data)
    ? workspaces.data
    : [];
  const activeWorkspace = workspaceList.find(
    (workspace) => workspace.id === activeWorkspaceId,
  );
  const profileDevice =
    activeWorkspace?.devices?.find((entry) => entry.device_id)?.device_id ??
    snapshot.data?.stack_demo?.profile.devices.find(
      (entry) => entry.device_id,
    )?.device_id ??
    "";
  const device = params.get("device") ?? profileDevice;
  const [license, setLicense] = useState("");
  const [minContext, setMinContext] = useState("");
  // Evidence-honesty toggle: models with no task benchmarks are excluded by
  // default (advisor-v2) and only surface when the visitor opts in.
  const showUnverified = params.get("unverified") === "1";
  const [liveAnswer, setLiveAnswer] = useState<AdvisorAnswer | null>(null);
  const [liveError, setLiveError] = useState<string | null>(null);

  function update(name: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(name, value);
    else next.delete(name);
    setParams(next, { replace: true });
    setLiveAnswer(null);
  }

  const staticAnswer =
    advisor && device ? (advisor.answers[`${task}|${device}`] ?? null) : null;

  async function fetchLive() {
    setLiveError(null);
    try {
      const answer = await apiFetch<AdvisorAnswer>("/api/v1/recommend", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          task,
          device,
          allowed_licenses: license ? [license] : null,
          min_context: minContext ? Number(minContext) : null,
          include_unverified: showUnverified,
        }),
      });
      setLiveAnswer(answer);
    } catch {
      setLiveError("Recommendation service is unavailable right now.");
    }
  }

  const answer = staticMode ? staticAnswer : (liveAnswer ?? staticAnswer);
  const minContextValue = minContext ? Number(minContext) : null;

  const { visible, policyExcluded } = useMemo(() => {
    if (!answer) {
      return { visible: [], policyExcluded: [] as Array<{ model_id: string; reason: string }> };
    }
    // In live mode with a fetched answer the API already applied policy;
    // over precomputed answers the same gates apply here, visibly.
    if (!staticMode && liveAnswer) {
      return { visible: liveAnswer.candidates, policyExcluded: [] };
    }
    const kept: AdvisorCandidate[] = [];
    const dropped: Array<{ model_id: string; reason: string }> = [];
    for (const candidate of answer.candidates) {
      const violation = candidatePassesPolicy(
        candidate,
        license,
        minContextValue,
      );
      if (violation) dropped.push({ model_id: candidate.model_id, reason: violation });
      else kept.push(candidate);
    }
    return { visible: kept, policyExcluded: dropped };
  }, [answer, license, liveAnswer, minContextValue, staticMode]);

  const licenses = useMemo(() => {
    const values = new Set<string>();
    for (const candidate of answer?.candidates ?? []) {
      if (candidate.license.value) values.add(candidate.license.value);
    }
    return [...values].sort();
  }, [answer]);

  if (snapshot.isLoading) {
    return <div className="loading-grid" aria-label="Loading advisor"><span /><span /></div>;
  }

  return (
    <section className="page-stack" aria-labelledby="advisor-title">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Decide · Advisor</p>
          <h1 id="advisor-title">What should you run?</h1>
          <p className="lede">
            Task, hardware, and policy in — a ranked shortlist out. Every
            component cites its engine: fit, tracked-set benchmarks, ring,
            license, and cost.
          </p>
        </div>
      </header>
      <div className="filter-bar" aria-label="Advisor inputs">
        <label>
          <span>Task</span>
          <select value={task} onChange={(event) => update("task", event.target.value)}>
            {Object.entries(advisor?.tasks ?? { coding: { label: "Coding assistant" } }).map(
              ([value, spec]) => (
                <option value={value} key={value}>
                  {spec.label}
                </option>
              ),
            )}
          </select>
        </label>
        <label>
          <span>Hardware</span>
          <select
            value={device}
            onChange={(event) => update("device", event.target.value)}
          >
            <option value="">Select device</option>
            {(advisor?.devices ?? []).map((id) => (
              <option value={id} key={id}>
                {id}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>License policy</span>
          <select value={license} onChange={(event) => { setLicense(event.target.value); setLiveAnswer(null); }}>
            <option value="">Any license</option>
            {licenses.map((value) => (
              <option value={value} key={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Min context</span>
          <select
            value={minContext}
            onChange={(event) => { setMinContext(event.target.value); setLiveAnswer(null); }}
          >
            {CONTEXT_CHOICES.map((choice) => (
              <option value={choice.value} key={choice.value}>
                {choice.label}
              </option>
            ))}
          </select>
        </label>
        <label className="toggle">
          <input
            type="checkbox"
            checked={showUnverified}
            onChange={(event) =>
              update("unverified", event.target.checked ? "1" : "")
            }
          />
          <span>Include benchmark-less models</span>
        </label>
        {!staticMode && (
          <button
            type="button"
            className="secondary-button"
            disabled={!device}
            onClick={() => void fetchLive()}
          >
            Recompute live
          </button>
        )}
      </div>
      {liveError && (
        <div className="error-state" role="alert">
          <strong>{liveError}</strong>
        </div>
      )}
      {!answer ? (
        <div className="empty-state">
          <strong>Pick a task and a device</strong>
          <span>
            Shortlists are precomputed for every task and device preset;
            policy filters apply on top, visibly.
          </span>
        </div>
      ) : (
        <>
          <p className="claim-meta">
            {answer.task_label} on {answer.device}
            {answer.cost.board_power_kw != null &&
              ` · ~${answer.cost.board_power_kw} kW board power`}
            {answer.cost.indicative_hardware_usd != null &&
              ` · indicative hardware $${answer.cost.indicative_hardware_usd}`}
            {" · "}
            <Link to="/planner">plan the workload →</Link>
          </p>
          <div className="try-grid">
            {visible.map((candidate, index) => (
              <article className="try-card" key={candidate.model_id}>
                <div className="try-card-head">
                  <Link
                    to={`/catalog/${encodeURIComponent(candidate.release_id)}`}
                    className="item-title"
                  >
                    {index + 1}. {candidate.name}
                  </Link>
                  {candidate.ring && (
                    <span className={`ring-pill pill-${candidate.ring}`}>
                      {candidate.ring}
                    </span>
                  )}
                  {candidate.evidence_tier === "single-source" && (
                    <span
                      className="ring-pill pill-watch"
                      title="Ranked from a single benchmark suite — below fully evidenced models"
                    >
                      insufficient evidence
                    </span>
                  )}
                  {candidate.evidence_tier === "none" && (
                    <span
                      className="ring-pill pill-avoid"
                      title="No tracked benchmark for this task; shown via opt-in"
                    >
                      unverified
                    </span>
                  )}
                  {candidate.estimated_tok_s != null && (
                    <span
                      className={`ring-pill ${candidate.estimated_tok_s < 8 ? "pill-watch" : "pill-pilot"}`}
                      title="Estimated decode speed from device memory bandwidth"
                    >
                      ~{candidate.estimated_tok_s} tok/s
                    </span>
                  )}
                </div>
                <p className="try-meta">
                  {formatParams(candidate.params_total, candidate.params_active) ?? "—"}
                  {" · "}
                  {formatContext(candidate.context_length) ?? "—"} context
                  {" · "}
                  {candidate.license.value ?? "license unknown"}
                </p>
                {candidate.task_capability && (
                  <p className="try-meta">
                    Task capability p{candidate.task_capability.percentile}
                    {" — "}
                    {candidate.task_capability.benchmarks
                      .map((benchmark) => `${benchmark.label}: ${benchmark.consensus}`)
                      .join(" · ")}
                  </p>
                )}
                <ul className="try-evidence">
                  {candidate.reasons.map((reason) => (
                    <li key={reason}>{reason}</li>
                  ))}
                  {candidate.assumptions.map((assumption) => (
                    <li key={assumption}>Assumption: {assumption}</li>
                  ))}
                </ul>
              </article>
            ))}
          </div>
          {!visible.length && (
            <div className="empty-state compact">
              <strong>No candidate passes this policy on this device</strong>
              <span>Loosen the license or context constraint, or pick larger hardware.</span>
            </div>
          )}
          {(policyExcluded.length > 0 || answer.excluded.length > 0) && (
            <details className="excluded-block">
              <summary>
                {policyExcluded.length + answer.excluded.length} excluded — every
                exclusion has a reason
              </summary>
              <ul className="try-evidence">
                {[...policyExcluded, ...answer.excluded].map((row) => (
                  <li key={`${row.model_id}-${row.reason}`}>
                    {row.model_id}: {row.reason}
                  </li>
                ))}
              </ul>
            </details>
          )}
          <p className="data-timestamp">
            Share this answer: the task and device live in the URL.
          </p>
        </>
      )}
    </section>
  );
}

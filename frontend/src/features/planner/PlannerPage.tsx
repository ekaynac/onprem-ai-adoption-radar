import { useMemo, useState } from "react";

import { apiFetch } from "../../api/client";
import { usePublicSnapshot } from "../catalog/catalogQueries";


type PlanResult = {
  feasible: boolean;
  n_gpus?: number;
  layout?: Record<string, unknown> | null;
  recipe?: string | null;
  tco?: Record<string, unknown> | null;
  reasons?: string[];
  assumptions?: string[];
} & Record<string, unknown>;

const VERDICT_LABELS: Record<string, string> = {
  fits: "Fits",
  fits_tight: "Fits (tight)",
  fits_quantized: "Fits quantized",
  wont_fit: "Won't fit",
  unknown: "Unknown",
};

export function PlannerPage({ staticMode = false }: { staticMode?: boolean }) {
  const snapshot = usePublicSnapshot(true);
  const planner = snapshot.data?.planner ?? null;
  const [modelId, setModelId] = useState("");
  const [device, setDevice] = useState("");
  const [concurrency, setConcurrency] = useState(32);
  const [context, setContext] = useState(8192);
  const [plan, setPlan] = useState<PlanResult | null>(null);
  const [planning, setPlanning] = useState(false);
  const [planError, setPlanError] = useState<string | null>(null);

  const models = useMemo(() => {
    const seen = new Map<string, string>();
    for (const fit of planner?.fits ?? []) {
      if (!seen.has(fit.model_id)) seen.set(fit.model_id, fit.model_id);
    }
    return [...seen.keys()].sort();
  }, [planner?.fits]);

  const fit = useMemo(
    () =>
      (planner?.fits ?? []).find(
        (row) => row.model_id === modelId && row.device === device,
      ) ?? null,
    [planner?.fits, modelId, device],
  );

  async function requestPlan() {
    setPlanning(true);
    setPlanError(null);
    try {
      const result = await apiFetch<PlanResult>("/api/v1/capacity/plan", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          model_id: modelId,
          device,
          concurrent_requests: concurrency,
          avg_context_tokens: context,
        }),
      });
      setPlan(result);
    } catch {
      setPlanError("Capacity planning is unavailable right now.");
    } finally {
      setPlanning(false);
    }
  }

  if (snapshot.isLoading) {
    return <div className="loading-grid" aria-label="Loading planner"><span /></div>;
  }

  return (
    <section className="page-stack" aria-labelledby="planner-title">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Decide · Deployment planner</p>
          <h1 id="planner-title">Turn evidence into an executable topology</h1>
          <p className="lede">
            Every verdict comes from the deterministic capacity engine — the
            same solver behind the CLI and MCP. Unknowns stay unknown.
          </p>
        </div>
      </header>
      {!planner ? (
        <div className="empty-state">
          <strong>Planner data unavailable</strong>
          <span>The published snapshot carries no fit grid yet.</span>
        </div>
      ) : (
        <div className="planner-grid">
          <section className="panel form-stack">
            <label>
              <span>Model</span>
              <select
                value={modelId}
                onChange={(event) => setModelId(event.target.value)}
              >
                <option value="">Select model</option>
                {models.map((id) => (
                  <option value={id} key={id}>
                    {id}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>Device</span>
              <select
                value={device}
                onChange={(event) => setDevice(event.target.value)}
              >
                <option value="">Select device</option>
                {(planner.devices ?? []).map((id) => (
                  <option value={id} key={id}>
                    {id}
                  </option>
                ))}
              </select>
            </label>
            {!staticMode && (
              <>
                <label>
                  <span>Concurrent requests</span>
                  <input
                    type="number"
                    min={1}
                    value={concurrency}
                    onChange={(event) =>
                      setConcurrency(Number(event.target.value))
                    }
                  />
                </label>
                <label>
                  <span>Context tokens</span>
                  <input
                    type="number"
                    min={1}
                    value={context}
                    onChange={(event) => setContext(Number(event.target.value))}
                  />
                </label>
                <button
                  type="button"
                  className="secondary-button"
                  disabled={!modelId || !device || planning}
                  onClick={() => void requestPlan()}
                >
                  {planning ? "Solving…" : "Plan workload"}
                </button>
              </>
            )}
          </section>
          <section className="panel plan-result" aria-live="polite">
            <p className="eyebrow">Fit verdict</p>
            {!fit ? (
              <div className="empty-state compact">
                <strong>Select a model and device</strong>
                <span>
                  Verdicts are precomputed at{" "}
                  {planner.context_tokens.toLocaleString()} context tokens.
                </span>
              </div>
            ) : (
              <>
                <strong className="plan-capacity">
                  {VERDICT_LABELS[fit.verdict] ?? fit.verdict}
                </strong>
                <div className="assumption-sheet">
                  <strong>Assumption sheet</strong>
                  {fit.best_quant_format && (
                    <span>Best fitting quant: {fit.best_quant_format}</span>
                  )}
                  {fit.best_quant_memory_gb != null && (
                    <span>
                      Estimated {fit.best_quant_memory_gb.toFixed(1)} GB of{" "}
                      {fit.usable_gb.toFixed(1)} GB usable
                    </span>
                  )}
                  <span>
                    {fit.context_tokens.toLocaleString()} token working context
                  </span>
                  {fit.note && <span>{fit.note}</span>}
                </div>
              </>
            )}
            {planError && (
              <div className="error-state" role="alert">
                <strong>{planError}</strong>
              </div>
            )}
            {plan && (
              <div className="assumption-sheet">
                <strong>
                  {plan.feasible
                    ? `Workload plan: ${plan.n_gpus} GPU${plan.n_gpus === 1 ? "" : "s"}`
                    : "Workload not feasible"}
                </strong>
                {(plan.reasons ?? []).map((reason) => (
                  <span key={reason}>{reason}</span>
                ))}
                {(plan.assumptions ?? []).map((assumption) => (
                  <span key={assumption}>{assumption}</span>
                ))}
                {typeof plan.recipe === "string" && plan.recipe && (
                  <pre className="recipe-block">{plan.recipe}</pre>
                )}
              </div>
            )}
          </section>
        </div>
      )}
    </section>
  );
}

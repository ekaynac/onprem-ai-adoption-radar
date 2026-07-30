import { useState } from "react";

import { useWorkspaces } from "../workspaces/WorkspaceSwitcher";
import { setActiveWorkspaceId } from "../workspaces/workspaceStore";


export function PlannerPage() {
  const workspaces = useWorkspaces();
  const [workspaceId, setWorkspaceId] = useState("");
  const [concurrency, setConcurrency] = useState(32);
  const [context, setContext] = useState(8192);
  const selected = (workspaces.data ?? []).find(
    (workspace) => workspace.id === workspaceId,
  );
  const h200Count = (selected?.devices ?? []).reduce(
    (total, device) =>
      total +
      (device.device_id === "hgx-h200-8" ? device.count * 8 : 0),
    0,
  );
  const feasible = h200Count > 0;

  if (workspaces.isLoading) {
    return <div className="loading-grid" aria-label="Loading workspaces"><span /></div>;
  }

  return (
    <section className="page-stack" aria-labelledby="planner-title">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Decide · Deployment planner</p>
          <h1 id="planner-title">Turn evidence into an executable topology</h1>
          <p className="lede">
            Capacity, policy, compatibility, and assumptions are evaluated
            together.
          </p>
        </div>
      </header>
      <div className="planner-grid">
        <section className="panel form-stack">
          <label>
            <span>Workspace</span>
            <select
              aria-label="Workspace"
              value={workspaceId}
              onChange={(event) => {
                setWorkspaceId(event.target.value);
                setActiveWorkspaceId(event.target.value);
              }}
            >
              <option value="">Select estate</option>
              {(workspaces.data ?? []).map((workspace) => (
                <option value={workspace.id} key={workspace.id}>
                  {workspace.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Concurrent requests</span>
            <input
              type="number"
              min={1}
              value={concurrency}
              onChange={(event) => setConcurrency(Number(event.target.value))}
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
        </section>
        <section className="panel plan-result" aria-live="polite">
          <p className="eyebrow">Estate result</p>
          {!selected ? (
            <div className="empty-state compact">
              <strong>Select a workspace</strong>
              <span>The plan will inherit its devices and policies.</span>
            </div>
          ) : feasible ? (
            <>
              <strong className="plan-capacity">{h200Count} × H200</strong>
              <p>Candidate topology for {concurrency} concurrent requests.</p>
              <div className="assumption-sheet">
                <strong>Assumption sheet</strong>
                <span>{context.toLocaleString()} token working context</span>
                <span>Tensor parallel topology requires verified platform support</span>
                <span>Launch recipe unlocks after model and platform qualification</span>
              </div>
            </>
          ) : (
            <div className="infeasible">
              <strong>Not feasible on current estate</strong>
              <span>Add a compatible accelerator pool or reduce the workload target.</span>
            </div>
          )}
        </section>
      </div>
    </section>
  );
}

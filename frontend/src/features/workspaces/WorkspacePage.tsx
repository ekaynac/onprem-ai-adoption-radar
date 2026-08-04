import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { apiFetch } from "../../api/client";
import {
  usePublicSnapshot,
  type AlertFeed,
  type StackProfileInfo,
} from "../catalog/catalogQueries";
import { useWorkspaces } from "./WorkspaceSwitcher";
import {
  setActiveWorkspaceId,
  useActiveWorkspaceId,
  type Workspace,
} from "./workspaceStore";


type WorkspaceInput = {
  name: string;
  devices?: Array<{ device_id: string; count: number }>;
  workloads?: Array<Record<string, unknown>>;
  policies?: Record<string, unknown>;
  watchlists?: Array<Record<string, unknown>>;
  stack?: {
    engines: Array<{ name: string; version?: string | null }>;
    models: string[];
    quant_formats: string[];
  };
};


function parseEngines(raw: string) {
  return raw
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean)
    .map((value) => {
      const [name, version] = value.split("@");
      return { name: name.trim(), version: version?.trim() || null };
    });
}


function parseList(raw: string) {
  return raw
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
}


export function AlertFeedPanel({
  feed: rawFeed,
  title,
}: {
  feed: AlertFeed | null | undefined;
  title: string;
}) {
  // Defensive: only trust a payload that actually looks like a feed.
  const feed =
    rawFeed && Array.isArray(rawFeed.alerts) && rawFeed.counts
      ? rawFeed
      : null;
  return (
    <section className="panel" aria-label={title}>
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Alerts · last {feed?.window_days ?? 14} days</p>
          <h2>{title}</h2>
        </div>
        {feed && (
          <div className="freshness-stamp">
            {feed.counts.act} act · {feed.counts.evaluate} evaluate
          </div>
        )}
      </div>
      {!feed || feed.alerts.length === 0 ? (
        <div className="empty-state">
          <strong>Silence — nothing touched this stack</strong>
          <span>
            Alerts only fire for events matching the profile's engines,
            models, quant formats, or devices.
          </span>
        </div>
      ) : (
        <ul className="brief-list">
          {feed.alerts.map((alert) => (
            <li key={alert.id}>
              <div className="brief-item-head">
                <strong>{alert.subject}</strong>
                <span className={`verdict-pill verdict-${alert.verdict}`}>
                  {alert.verdict === "act" ? "Act" : "Evaluate"}
                </span>
              </div>
              <p>{alert.what_happened}</p>
              <p className="claim-meta">
                Matched: {alert.matched_components.join(", ")} ·{" "}
                {alert.event_type}
                {alert.receipts.map((receipt) =>
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
      )}
    </section>
  );
}


function StackSummary({ profile }: { profile: StackProfileInfo }) {
  return (
    <section className="panel">
      <p className="eyebrow">Demo profile</p>
      <h2>{profile.name}</h2>
      <p className="claim-meta">
        Estate:{" "}
        {profile.devices
          .map((device) => `${device.count}× ${device.device_id ?? "custom"}`)
          .join(", ")}
      </p>
      <p className="claim-meta">
        {profile.stack.engines.map((engine) => (
          <span className="lineage-chip" key={engine.name}>
            {engine.name}
            {engine.version ? ` ${engine.version}` : ""}
          </span>
        ))}
        {profile.stack.models.map((model) => (
          <span className="lineage-chip" key={model}>
            {model}
          </span>
        ))}
        {profile.stack.quant_formats.map((quant) => (
          <span className="lineage-chip" key={quant}>
            {quant}
          </span>
        ))}
      </p>
    </section>
  );
}


export function WorkspacePage({
  staticMode = import.meta.env.MODE === "static",
}: {
  staticMode?: boolean;
}) {
  const snapshot = usePublicSnapshot(staticMode);
  const workspaces = useWorkspaces(!staticMode);
  const activeWorkspaceId = useActiveWorkspaceId();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [deviceId, setDeviceId] = useState("");
  const [engines, setEngines] = useState("");
  const [models, setModels] = useState("");
  const [quants, setQuants] = useState("");
  const [error, setError] = useState("");
  const importRef = useRef<HTMLInputElement>(null);

  const workspaceList = Array.isArray(workspaces.data)
    ? workspaces.data
    : [];
  const activeWorkspace = workspaceList.find(
    (workspace) => workspace.id === activeWorkspaceId,
  );
  const liveAlerts = useQuery({
    queryKey: ["workspace-alerts", activeWorkspaceId],
    queryFn: ({ signal }) =>
      apiFetch<AlertFeed>(
        `/api/v1/workspaces/${encodeURIComponent(activeWorkspaceId ?? "")}/alerts`,
        { signal },
      ),
    enabled: !staticMode && Boolean(activeWorkspaceId),
  });

  const create = useMutation({
    mutationFn: (value: WorkspaceInput) =>
      apiFetch<Workspace>("/api/v1/workspaces", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(value),
      }),
    onSuccess: async (workspace) => {
      setActiveWorkspaceId(workspace.id);
      setName("");
      setDeviceId("");
      setEngines("");
      setModels("");
      setQuants("");
      setError("");
      await queryClient.invalidateQueries({ queryKey: ["workspaces"] });
      await queryClient.invalidateQueries({
        queryKey: ["workspace-alerts"],
      });
    },
    onError: (failure) => setError(String(failure)),
  });
  const remove = useMutation({
    mutationFn: (workspaceId: string) =>
      apiFetch<void>(
        `/api/v1/workspaces/${encodeURIComponent(workspaceId)}`,
        { method: "DELETE" },
      ),
    onSuccess: async (_data, workspaceId) => {
      if (activeWorkspaceId === workspaceId) {
        setActiveWorkspaceId(undefined);
      }
      await queryClient.invalidateQueries({ queryKey: ["workspaces"] });
    },
    onError: (failure) => setError(String(failure)),
  });

  function save() {
    if (!name.trim()) return;
    create.mutate({
      name: name.trim(),
      devices: deviceId
        ? [{ device_id: deviceId.trim(), count: 1 }]
        : [],
      stack: {
        engines: parseEngines(engines),
        models: parseList(models),
        quant_formats: parseList(quants),
      },
    });
  }

  function exportWorkspace(workspace: Workspace) {
    const { id: _id, ...workspaceDocument } = workspace;
    void _id;
    const blob = new Blob(
      [
        JSON.stringify(
          { schema_version: 1, workspace: workspaceDocument },
          null,
          2,
        ),
      ],
      { type: "application/json" },
    );
    const anchor = document.createElement("a");
    anchor.href = URL.createObjectURL(blob);
    anchor.download = `${workspace.name.toLowerCase().replaceAll(" ", "-")}.json`;
    anchor.click();
    URL.revokeObjectURL(anchor.href);
  }

  async function importWorkspace(file?: File) {
    if (!file) return;
    try {
      const document = JSON.parse(await file.text()) as {
        schema_version: number;
        workspace: WorkspaceInput;
      };
      if (document.schema_version !== 1 || !document.workspace?.name) {
        throw new Error("Unsupported workspace document");
      }
      create.mutate(document.workspace);
    } catch (failure) {
      setError(String(failure));
    }
  }

  if (staticMode) {
    const demo = snapshot.data?.stack_demo ?? null;
    return (
      <section className="page-stack" aria-labelledby="workspace-title">
        <header className="page-heading">
          <div>
            <p className="eyebrow">Stack profile · Demo</p>
            <h1 id="workspace-title">Alerts are diffed against a stack</h1>
            <p className="lede">
              This reference profile shows the mechanism: an event only
              alerts if it touches an engine, model, quant format, or
              device you actually run. Run the radar locally to define
              your own profiles — no account, no login.
            </p>
          </div>
        </header>
        {!demo ? (
          <div className="empty-state">
            <strong>No demo profile in this snapshot</strong>
            <span>The next publish cycle ships it.</span>
          </div>
        ) : (
          <div className="workspace-grid">
            <StackSummary profile={demo.profile} />
            <AlertFeedPanel
              feed={demo.alerts}
              title="What touched this stack"
            />
          </div>
        )}
      </section>
    );
  }

  return (
    <section className="page-stack" aria-labelledby="workspace-title">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Workspace · Stack profiles</p>
          <h1 id="workspace-title">Describe the estate and the stack</h1>
          <p className="lede">
            Estate (devices) + running stack (engines, models, quant
            formats). Alerts and the weekly brief are diffed against it.
            No account, login, or role administration.
          </p>
        </div>
      </header>
      <div className="workspace-grid">
        <section className="panel">
          <p className="eyebrow">New profile</p>
          <h2>Infrastructure context</h2>
          <div className="form-stack">
            <label>
              <span>Profile name</span>
              <input value={name} onChange={(event) => setName(event.target.value)} />
            </label>
            <label>
              <span>Primary device ID (optional)</span>
              <input
                value={deviceId}
                onChange={(event) => setDeviceId(event.target.value)}
                placeholder="rtx-4090-24gb"
              />
            </label>
            <label>
              <span>Engines (comma, name@version)</span>
              <input
                value={engines}
                onChange={(event) => setEngines(event.target.value)}
                placeholder="vllm@0.10, ollama"
              />
            </label>
            <label>
              <span>Models in production (comma)</span>
              <input
                value={models}
                onChange={(event) => setModels(event.target.value)}
                placeholder="qwen3-32b, deepseek-r1"
              />
            </label>
            <label>
              <span>Quant formats (comma)</span>
              <input
                value={quants}
                onChange={(event) => setQuants(event.target.value)}
                placeholder="gguf, awq"
              />
            </label>
            <button
              className="primary-button"
              disabled={!name.trim() || create.isPending}
              onClick={save}
              type="button"
            >
              Save profile
            </button>
            {error && <p className="form-error" role="alert">{error}</p>}
          </div>
        </section>
        <section className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Profiles</p>
              <h2>Local decision contexts</h2>
            </div>
            <button
              className="secondary-button"
              onClick={() => importRef.current?.click()}
              type="button"
            >
              Import
            </button>
            <input
              ref={importRef}
              className="sr-only"
              type="file"
              aria-label="Import workspace file"
              accept="application/json"
              onChange={(event) => void importWorkspace(event.target.files?.[0])}
            />
          </div>
          <div className="workspace-list">
            {(workspaces.data ?? []).map((workspace) => (
              <article key={workspace.id}>
                <div>
                  <strong>{workspace.name}</strong>
                  <span>
                    {workspace.devices?.length ?? 0} estate entries ·{" "}
                    {(workspace.stack?.engines?.length ?? 0) +
                      (workspace.stack?.models?.length ?? 0)}{" "}
                    stack entries
                  </span>
                </div>
                <div>
                  <button
                    className="text-button"
                    onClick={() => setActiveWorkspaceId(workspace.id)}
                    type="button"
                  >
                    Activate
                  </button>
                  <button
                    className="text-button"
                    onClick={() => exportWorkspace(workspace)}
                    type="button"
                  >
                    Export
                  </button>
                  <button
                    className="text-button"
                    onClick={() => remove.mutate(workspace.id)}
                    type="button"
                  >
                    Delete
                  </button>
                </div>
              </article>
            ))}
          </div>
        </section>
      </div>
      {activeWorkspace && (
        <AlertFeedPanel
          feed={liveAlerts.data}
          title={`What touched “${activeWorkspace.name}”`}
        />
      )}
    </section>
  );
}

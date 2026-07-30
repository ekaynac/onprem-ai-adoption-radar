import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { apiFetch } from "../../api/client";
import { useWorkspaces } from "./WorkspaceSwitcher";
import {
  setActiveWorkspaceId,
  type Workspace,
} from "./workspaceStore";


type WorkspaceInput = {
  name: string;
  devices?: Array<{ device_id: string; count: number }>;
  workloads?: Array<Record<string, unknown>>;
  policies?: Record<string, unknown>;
  watchlists?: Array<Record<string, unknown>>;
};


export function WorkspacePage() {
  const workspaces = useWorkspaces();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [deviceId, setDeviceId] = useState("");
  const [error, setError] = useState("");
  const importRef = useRef<HTMLInputElement>(null);
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
      setError("");
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

  return (
    <section className="page-stack" aria-labelledby="workspace-title">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Workspace · Local profiles</p>
          <h1 id="workspace-title">Describe the estate, not identities</h1>
          <p className="lede">
            Multiple local architecture profiles. No account, login, or role
            administration.
          </p>
        </div>
      </header>
      <div className="workspace-grid">
        <section className="panel">
          <p className="eyebrow">New workspace</p>
          <h2>Infrastructure context</h2>
          <div className="form-stack">
            <label>
              <span>Workspace name</span>
              <input value={name} onChange={(event) => setName(event.target.value)} />
            </label>
            <label>
              <span>Primary device ID (optional)</span>
              <input
                value={deviceId}
                onChange={(event) => setDeviceId(event.target.value)}
                placeholder="hgx-h200-8"
              />
            </label>
            <button
              className="primary-button"
              disabled={!name.trim() || create.isPending}
              onClick={save}
              type="button"
            >
              Save workspace
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
              accept="application/json"
              onChange={(event) => void importWorkspace(event.target.files?.[0])}
            />
          </div>
          <div className="workspace-list">
            {(workspaces.data ?? []).map((workspace) => (
              <article key={workspace.id}>
                <div>
                  <strong>{workspace.name}</strong>
                  <span>{workspace.devices?.length ?? 0} estate entries</span>
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
                </div>
              </article>
            ))}
          </div>
        </section>
      </div>
    </section>
  );
}

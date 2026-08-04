import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { apiFetch } from "../../api/client";
import {
  setActiveWorkspaceId,
  useActiveWorkspaceId,
  type Workspace,
} from "./workspaceStore";


export function useWorkspaces(enabled = true) {
  return useQuery({
    queryKey: ["workspaces"],
    queryFn: ({ signal }) =>
      apiFetch<Workspace[]>("/api/v1/workspaces", { signal }),
    enabled,
  });
}


export function WorkspaceSwitcher() {
  const workspaces = useWorkspaces();
  const activeId = useActiveWorkspaceId();
  const queryClient = useQueryClient();

  useEffect(() => {
    const items = workspaces.data ?? [];
    if (activeId && !items.some((item) => item.id === activeId)) {
      setActiveWorkspaceId(items[0]?.id);
    }
  }, [activeId, workspaces.data]);

  async function change(value: string) {
    setActiveWorkspaceId(value || undefined);
    await queryClient.invalidateQueries({
      predicate: (query) =>
        [
          "releases",
          "catalog",
          "catalog-detail",
          "deployment-fit",
          "planner",
          "comparison",
          "watchlists",
        ].includes(String(query.queryKey[0])),
    });
  }

  return (
    <label className="workspace-switcher">
      <span className="sr-only">Workspace</span>
      <select
        aria-label="Workspace"
        value={activeId ?? ""}
        onChange={(event) => void change(event.target.value)}
      >
        <option value="">Public baseline</option>
        {(workspaces.data ?? []).map((workspace) => (
          <option key={workspace.id} value={workspace.id}>
            {workspace.name}
          </option>
        ))}
      </select>
    </label>
  );
}

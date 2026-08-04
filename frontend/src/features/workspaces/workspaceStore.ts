import { useSyncExternalStore } from "react";

import type { components } from "../../api/generated/schema";


export type Workspace = components["schemas"]["Workspace"];
export const ACTIVE_WORKSPACE_KEY = "onprem-radar.active-workspace.v1";
const CHANGE_EVENT = "onprem-radar:workspace-change";


export function getActiveWorkspaceId() {
  try {
    return window.localStorage.getItem(ACTIVE_WORKSPACE_KEY) ?? undefined;
  } catch {
    return undefined;
  }
}


export function setActiveWorkspaceId(workspaceId?: string) {
  try {
    if (workspaceId) {
      window.localStorage.setItem(ACTIVE_WORKSPACE_KEY, workspaceId);
    } else {
      window.localStorage.removeItem(ACTIVE_WORKSPACE_KEY);
    }
  } catch {
    // Storage can be unavailable (private mode, hardened browsers);
    // activation is a convenience, not a requirement.
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}


function subscribe(callback: () => void) {
  window.addEventListener(CHANGE_EVENT, callback);
  window.addEventListener("storage", callback);
  return () => {
    window.removeEventListener(CHANGE_EVENT, callback);
    window.removeEventListener("storage", callback);
  };
}


export function useActiveWorkspaceId() {
  return useSyncExternalStore(
    subscribe,
    getActiveWorkspaceId,
    () => undefined,
  );
}

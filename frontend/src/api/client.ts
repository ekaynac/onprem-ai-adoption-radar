import type { paths } from "./generated/schema";


export type ApiPaths = paths;


export async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
  workspaceId?: string,
): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");
  if (workspaceId) {
    headers.set("X-Workspace-Id", workspaceId);
  }
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    throw new Error(`${response.status} ${await response.text()}`);
  }
  return response.json() as Promise<T>;
}

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

import { ComparePage } from "./ComparePage";


test("searches the complete catalog before offering compare candidates", async () => {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    const items = url.includes("q=Kimi+K3")
      ? [{
          release_id: "release:kimi-k3",
          name: "Kimi K3",
          category: "multimodal",
          lane: "deployable_onprem",
          lifecycle: "verified",
          first_observed_at: "2026-08-03T08:00:00Z",
          public_recommendation: { ring: "pilot" },
          workspace_recommendation: null,
        }]
      : [];
    return Promise.resolve(new Response(JSON.stringify({ items, next_cursor: null }), { status: 200 }));
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter><ComparePage /></MemoryRouter>
    </QueryClientProvider>,
  );

  await user.type(screen.getByRole("searchbox", { name: "Find models to compare" }), "Kimi K3");

  expect(await screen.findByText("Kimi K3")).toBeVisible();
  vi.unstubAllGlobals();
});


test("preserves selected models while searching for another candidate", async () => {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    const match = url.includes("q=Kimi")
      ? [catalogItem("release:kimi", "Kimi")]
      : url.includes("q=Qwen")
        ? [catalogItem("release:qwen", "Qwen")]
        : [];
    return Promise.resolve(new Response(JSON.stringify({ items: match, next_cursor: null }), { status: 200 }));
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter><ComparePage /></MemoryRouter>
    </QueryClientProvider>,
  );

  const search = screen.getByRole("searchbox", { name: "Find models to compare" });
  await user.type(search, "Kimi");
  await user.click(await screen.findByRole("checkbox", { name: "Kimi" }));
  await user.clear(search);
  await user.type(search, "Qwen");
  await user.click(await screen.findByRole("checkbox", { name: "Qwen" }));

  expect(screen.getByRole("heading", { name: "Kimi" })).toBeVisible();
  expect(screen.getByRole("heading", { name: "Qwen" })).toBeVisible();
  vi.unstubAllGlobals();
});


function catalogItem(releaseId: string, name: string) {
  return {
    release_id: releaseId,
    name,
    category: "text_reasoning",
    lane: "onprem_adjacent",
    lifecycle: "detected",
    first_observed_at: "2026-08-03T08:00:00Z",
    public_recommendation: { ring: null },
    workspace_recommendation: null,
  };
}

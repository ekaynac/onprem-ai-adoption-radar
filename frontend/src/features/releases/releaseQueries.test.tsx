import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

import { usePriorityReleases } from "./releaseQueries";


function SharedQueries() {
  const stream = usePriorityReleases(undefined, 50, false);
  const priority = usePriorityReleases(undefined, 50, true);
  return (
    <>
      <span>{stream.data?.items[0]?.name}</span>
      <span>{priority.data?.items[0]?.name}</span>
    </>
  );
}


test("keeps general and priority release results in separate cache entries", async () => {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const priority = String(input).includes("priority_only=true");
    return Promise.resolve(new Response(JSON.stringify({
      items: [{ name: priority ? "Priority result" : "General result" }],
      next_cursor: null,
    }), { status: 200 }));
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  render(
    <QueryClientProvider client={client}>
      <SharedQueries />
    </QueryClientProvider>,
  );

  expect(await screen.findByText("General result")).toBeVisible();
  expect(await screen.findByText("Priority result")).toBeVisible();
  expect(vi.mocked(fetch)).toHaveBeenCalledTimes(2);
  vi.unstubAllGlobals();
});

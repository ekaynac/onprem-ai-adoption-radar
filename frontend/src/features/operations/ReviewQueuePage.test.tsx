import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

import { ReviewQueuePage } from "./ReviewQueuePage";


test("shows review exceptions as the only manual attention queue", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        new Response(
          JSON.stringify([
            {
              id: "review:kimi:license",
              subject_id: "release:kimi-k3",
              code: "conflicting_authoritative_claims",
              message: "Official license claims differ",
              evidence_ids: ["evidence:one"],
              opened_at: "2026-07-30T10:00:00Z",
              resolved_at: null,
            },
          ]),
          { status: 200 },
        ),
      ),
    ),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  render(
    <QueryClientProvider client={client}>
      <ReviewQueuePage />
    </QueryClientProvider>,
  );

  expect(await screen.findByText("Official license claims differ")).toBeVisible();
  expect(screen.getByRole("button", { name: "Accept source 1" })).toBeVisible();
  vi.unstubAllGlobals();
});

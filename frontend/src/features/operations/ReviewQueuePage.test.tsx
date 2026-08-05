import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

import { ReviewQueuePage } from "./ReviewQueuePage";


test("shows review exceptions as the only manual attention queue", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      if (String(input).includes("lineage-suggestions")) {
        return Promise.resolve(
          new Response(
            JSON.stringify([
              {
                id: "lineage:release:child:quantized:hf:acme/model-x",
                child_release_id: "release:child",
                parent_external_ref: "hf:acme/Model-X",
                parent_release_id: null,
                relation: "quantized",
                confidence: 0.5,
              },
              {
                id: "lineage:release:other:converted:hf:acme/model-y",
                child_release_id: "release:other",
                parent_external_ref: "hf:acme/Model-Y",
                parent_release_id: null,
                relation: "converted",
                confidence: 0.5,
              },
            ]),
            { status: 200 },
          ),
        );
      }
      return Promise.resolve(
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
      );
    }),
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
  // Tier-3 lineage suggestions render with one-click decisions.
  expect(
    await screen.findByText("release:child → acme/Model-X"),
  ).toBeVisible();
  expect(
    screen.getAllByRole("button", { name: "Confirm parent" }),
  ).toHaveLength(2);
  expect(screen.getAllByRole("button", { name: "Reject" })).toHaveLength(2);
  // Triage accelerators: total count, relation group headers, HF links.
  expect(screen.getByText(/2 open/)).toBeVisible();
  expect(screen.getByText("quantized · 1 suggestion")).toBeVisible();
  expect(screen.getByText("converted · 1 suggestion")).toBeVisible();
  const hfLinks = screen.getAllByRole("link", {
    name: /Verify parent on Hugging Face/,
  });
  expect(hfLinks[0]).toHaveAttribute(
    "href",
    "https://huggingface.co/acme/Model-X",
  );
  vi.unstubAllGlobals();
});

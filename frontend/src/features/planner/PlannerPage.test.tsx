import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

import { PlannerPage } from "./PlannerPage";


test("switching workspace recomputes the plan and recommendation", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/workspaces")) {
        return Promise.resolve(
          new Response(
            JSON.stringify([
              {
                id: "workspace:dc",
                schema_version: 1,
                name: "Datacenter",
                devices: [{ device_id: "hgx-h200-8", count: 2 }],
                workloads: [],
                policies: {},
                watchlists: [],
              },
              {
                id: "workspace:laptop",
                schema_version: 1,
                name: "Laptop",
                devices: [{ device_id: "rtx-4090-24gb", count: 1 }],
                workloads: [],
                policies: {},
                watchlists: [],
              },
            ]),
            { status: 200 },
          ),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify({ items: [], next_cursor: null }), {
          status: 200,
        }),
      );
    }),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const user = userEvent.setup();

  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <PlannerPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );

  await user.selectOptions(
    await screen.findByLabelText("Workspace"),
    "workspace:dc",
  );
  expect(await screen.findByText("16 × H200")).toBeVisible();
  await user.selectOptions(
    screen.getByLabelText("Workspace"),
    "workspace:laptop",
  );
  expect(await screen.findByText("Not feasible on current estate")).toBeVisible();
  vi.unstubAllGlobals();
});

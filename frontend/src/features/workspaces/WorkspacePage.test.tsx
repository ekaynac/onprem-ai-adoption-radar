import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import { WorkspacePage } from "./WorkspacePage";


test("workspace creation requires no account fields", async () => {
  let workspaces: unknown[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        const created = {
          id: "workspace:ai-lab",
          schema_version: 1,
          devices: [],
          workloads: [],
          policies: {},
          watchlists: [],
          ...body,
        };
        workspaces = [created];
        return Promise.resolve(
          new Response(JSON.stringify(created), { status: 201 }),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify(workspaces), { status: 200 }),
      );
    }),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const user = userEvent.setup();

  render(
    <QueryClientProvider client={client}>
      <WorkspacePage />
    </QueryClientProvider>,
  );

  expect(screen.queryByLabelText(/email|password|user/i)).not.toBeInTheDocument();
  await user.type(screen.getByLabelText("Workspace name"), "AI Lab");
  await user.click(screen.getByRole("button", { name: "Save workspace" }));
  expect(await screen.findByText("AI Lab")).toBeVisible();
  vi.unstubAllGlobals();
});

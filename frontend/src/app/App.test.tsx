import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

import { App } from "./App";
import { AppProviders } from "./providers";
import { Sidebar } from "./shell/Sidebar";


test("renders the architect workspace navigation", () => {
  vi.stubGlobal("fetch", vi.fn(() => new Promise(() => undefined)));
  render(
    <AppProviders>
      <MemoryRouter initialEntries={["/overview"]}>
        <App />
      </MemoryRouter>
    </AppProviders>,
  );

  expect(screen.getByRole("navigation", { name: "Primary" })).toBeVisible();
  expect(screen.getByRole("link", { name: "Rings overview" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  expect(screen.getByRole("link", { name: "Answer Machine" })).toBeVisible();
  expect(screen.getByRole("link", { name: "GitHub projects" })).toBeVisible();
  expect(screen.getByText("What changed since your last visit")).toBeVisible();
  vi.unstubAllGlobals();
});


test("static mode removes private workspace and mutation navigation", () => {
  vi.stubGlobal("fetch", vi.fn(() => new Promise(() => undefined)));
  render(
    <AppProviders>
      <MemoryRouter initialEntries={["/overview"]}>
        <App staticMode />
      </MemoryRouter>
    </AppProviders>,
  );

  expect(screen.queryByRole("link", { name: "Workspace profiles" })).toBeNull();
  // The planner is read-only in static mode and stays in the nav.
  expect(
    screen.getByRole("link", { name: "Deployment planner" }),
  ).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Review queue" })).toBeNull();
  expect(screen.queryByRole("combobox", { name: "Active workspace" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Review exceptions" })).toBeNull();
  vi.unstubAllGlobals();
});


test("static operations page does not link to the disabled review route", () => {
  vi.stubGlobal("fetch", vi.fn(() => new Promise(() => undefined)));
  render(
    <AppProviders>
      <MemoryRouter initialEntries={["/operations"]}>
        <App staticMode />
      </MemoryRouter>
    </AppProviders>,
  );

  expect(screen.queryByRole("link", { name: /Review queue/ })).toBeNull();
  vi.unstubAllGlobals();
});


test("classic radar links are sibling documents with the latest digest", async () => {
  const queryClient = new QueryClient();
  queryClient.setQueryData(["public-snapshot"], {
    source_health: { source_health: [] },
    latest_digest: {
      generated_at: "2026-07-31T08:00:00Z",
      html_url: "digests/digest_2026-W31.html",
      card_url: "digests/cards/trending_og.png",
    },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/overview"]}>
        <Sidebar staticMode />
      </MemoryRouter>
    </QueryClientProvider>,
  );

  expect(await screen.findByText("Classic radar")).toBeVisible();
  for (const [name, href] of [
    ["Classic models", "models.html"],
    ["Classic platforms", "platforms.html"],
    ["Classic techniques", "techniques.html"],
    ["Classic trending", "trending.html"],
    ["Classic history", "history.html"],
    ["Classic compare", "compare.html"],
    ["Latest weekly digest", "digests/digest_2026-W31.html"],
  ]) {
    expect(screen.getByRole("link", { name })).toHaveAttribute("href", href);
  }
});

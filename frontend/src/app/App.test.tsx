import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

import { App } from "./App";
import { AppProviders } from "./providers";


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
  expect(screen.getByRole("link", { name: "Overview" })).toHaveAttribute(
    "aria-current",
    "page",
  );
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
  expect(screen.queryByRole("link", { name: "Deployment planner" })).toBeNull();
  expect(screen.queryByRole("link", { name: "Review queue" })).toBeNull();
  expect(screen.queryByRole("combobox", { name: "Active workspace" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Review exceptions" })).toBeNull();
  vi.unstubAllGlobals();
});

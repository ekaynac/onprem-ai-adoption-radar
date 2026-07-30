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
  expect(screen.getByText("What changed since your last visit")).toBeVisible();
  vi.unstubAllGlobals();
});

import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { App } from "./App";


test("renders the architect workspace navigation", () => {
  render(
    <MemoryRouter initialEntries={["/overview"]}>
      <App />
    </MemoryRouter>,
  );

  expect(screen.getByRole("navigation", { name: "Primary" })).toBeVisible();
  expect(screen.getByRole("link", { name: "Overview" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  expect(screen.getByText("What changed since your last visit")).toBeVisible();
});

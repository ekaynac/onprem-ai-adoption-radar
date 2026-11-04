import { render, screen, within } from "@testing-library/react";
import { vi } from "vitest";

import { view } from "../features/pulse/testData";
import { App } from "./App";
import { AppProviders } from "./providers";


afterEach(() => {
  vi.unstubAllGlobals();
});


function renderApp(data = view()) {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify(data)))));
  render(
    <AppProviders>
      <App />
    </AppProviders>,
  );
}


test("the sidebar links every lane and its feed", async () => {
  renderApp();
  const lanes = screen.getByRole("navigation", { name: "Lanes" });
  for (const name of ["Models", "Papers", "Repositories", "News"]) {
    expect(within(lanes).getByRole("link", { name: new RegExp(`^${name}( \\d+)?$`) })).toBeVisible();
  }
  expect(within(lanes).getByRole("link", { name: "All lanes (RSS)" })).toHaveAttribute(
    "href",
    "pulse.xml",
  );
  expect(await screen.findByText("1 sources healthy")).toBeVisible();
});


test("source health in the sidebar comes from the Pulse view", async () => {
  const data = view();
  data.health.sources.push({
    source: "news:feeds", status: "partial", count: 120, observed_at: data.generated_at,
  });
  renderApp(data);
  expect(await screen.findByText("1 of 2 sources need attention")).toBeVisible();
});


test("a view without a source report never claims health", async () => {
  const data = view();
  data.health.sources = [];
  renderApp(data);
  expect(await screen.findByText("No source report yet")).toBeVisible();
});


test("the footer credits the author and Mega", async () => {
  renderApp();
  const footer = screen.getByRole("contentinfo");
  expect(within(footer).getByText(/Built by Enes Kaynakcı/)).toBeVisible();
  expect(
    within(footer).getByRole("link", { name: "Mega Bilgisayar Tic. Ltd. Şti." }),
  ).toHaveAttribute("href", "https://www.megabilgisayar.com.tr");
});

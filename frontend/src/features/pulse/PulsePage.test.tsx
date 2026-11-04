import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { vi } from "vitest";

import { PulsePage } from "./PulsePage";
import type { PulseView } from "./pulseQueries";
import { GENERATED, view } from "./testData";


afterEach(() => {
  vi.unstubAllGlobals();
});


function renderWith(data: PulseView | null) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        data ? new Response(JSON.stringify(data)) : new Response("nope", { status: 500 }),
      ),
    ),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <PulsePage />
    </QueryClientProvider>,
  );
}


test("renders every lane with reasons, and the lab launch first", async () => {
  renderWith(view());

  const news = await screen.findByRole("region", { name: /News/ });
  const items = within(news).getAllByRole("listitem");
  expect(items[0]).toHaveTextContent("Introducing GPT-6.1 Sol");
  expect(items[0]).toHaveTextContent("model-release (1.00) · openai-news x1.5");
  expect(screen.getByRole("heading", { name: "New models (1)" })).toBeVisible();
  expect(screen.getByText("XiaomiMiMo/MiMo-V2.6-Pro-RL")).toBeVisible();
  expect(screen.getAllByText("Nothing new in this period")).toHaveLength(2);
});


test("shows the first 15 and reveals all on request, filtered items included", async () => {
  renderWith(view());

  const news = await screen.findByRole("region", { name: /News/ });
  // 19 of 20 are inside the default 7-day window.
  expect(within(news).getAllByRole("listitem").filter((li) => li.closest("ol"))).toHaveLength(15);
  fireEvent.click(within(news).getByRole("button", { name: "Show all 19" }));
  expect(within(news).getAllByRole("listitem").filter((li) => li.closest("ol"))).toHaveLength(19);
  expect(within(news).getByText("1 item(s) filtered out, with the reason for each")).toBeInTheDocument();
  expect(within(news).getByText("Airbnb widens access")).toBeInTheDocument();
  expect(within(news).getByText("1 item(s) the classifier was unsure about")).toBeInTheDocument();
});


test("the period filter widens to everything in the window", async () => {
  renderWith(view());

  await screen.findByRole("region", { name: /News/ });
  fireEvent.change(screen.getByLabelText("Period"), { target: { value: "all" } });
  fireEvent.click(screen.getByRole("button", { name: "Show all 20" }));
  expect(screen.getByText("Old news")).toBeVisible();
});


test("degraded triage and failing sources are announced, never silent", async () => {
  renderWith(view({
    health: {
      sources: [{ source: "huggingface:daily-papers", status: "error", count: 0, observed_at: GENERATED }],
      engines: { rules: 20 },
      degraded: true,
    },
  }));

  const status = await screen.findByRole("status");
  expect(status).toHaveTextContent("Triage degraded");
  expect(status).toHaveTextContent("huggingface:daily-papers: error (0 items)");
});


test("a missing pulse file shows an explicit error", async () => {
  renderWith(null);

  expect(await screen.findByRole("alert")).toHaveTextContent("Pulse is unavailable right now");
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

import { CatalogPage } from "./CatalogPage";


test("filters all six model categories", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({ items: [], next_cursor: null }),
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
      <MemoryRouter>
        <CatalogPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );

  const category = screen.getByLabelText("Model category");
  for (const name of [
    "Text & reasoning",
    "Multimodal",
    "Embedding & reranking",
    "Speech & audio",
    "Image & video",
    "Vision & documents",
  ]) {
    expect(within(category).getByRole("option", { name })).toBeVisible();
  }
  vi.unstubAllGlobals();
});


test("sends the selected lane to catalog search", async () => {
  const fetchMock = vi.fn(() =>
    Promise.resolve(
      new Response(JSON.stringify({ items: [], next_cursor: null }), {
        status: 200,
      }),
    ),
  );
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const user = userEvent.setup();

  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <CatalogPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await user.selectOptions(screen.getByLabelText("Lane"), "market_reference");

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("lane=market_reference"),
      expect.anything(),
    );
  });
  vi.unstubAllGlobals();
});

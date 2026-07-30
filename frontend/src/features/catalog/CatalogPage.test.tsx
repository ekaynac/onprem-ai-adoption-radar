import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
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

import { render, screen } from "@testing-library/react";

import { IntegrationsPage } from "./IntegrationsPage";


test("offers the durable histories and public subscription feeds", () => {
  render(<IntegrationsPage />);

  for (const [name, href] of [
    ["Project history", "history.jsonl"],
    ["Model history", "model-history.jsonl"],
    ["Technique history", "technique-history.jsonl"],
    ["Trending observations", "trending-observations.jsonl"],
    ["Unified changes · RSS", "changes.rss"],
    ["Unified changes · JSON Feed", "changes.json"],
    ["Unified changes · Atom", "changes.xml"],
    ["Model changes · Atom", "changes-models.xml"],
    ["Research changes · Atom", "changes-research.xml"],
    ["Weekly digest · Atom", "digests/digest.xml"],
    ["Weekly digest · RSS", "digests/digest-rss.xml"],
  ]) {
    expect(screen.getByRole("link", { name })).toHaveAttribute("href", href);
  }
  expect(screen.getByText(/uv run radar mcp/)).toBeVisible();
  expect(screen.getByRole("link", { name: "Interactive API documentation" })).toHaveAttribute(
    "href",
    "/api/docs",
  );
});

test("does not advertise live API endpoints in a static export", () => {
  render(<IntegrationsPage staticMode />);

  expect(
    screen.queryByRole("link", { name: "Interactive API documentation" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("link", { name: "OpenAPI schema" }),
  ).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Public snapshot" })).toHaveAttribute(
    "href",
    "data/public-snapshot.v1.json",
  );
  expect(screen.getByText(/start the live command center/i)).toBeVisible();
});

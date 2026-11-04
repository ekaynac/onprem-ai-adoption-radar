import type { PulseRow } from "./pulseQueries";


export const LANES: ReadonlyArray<PulseRow["lane"]> = ["model", "paper", "repo", "news"];

export const LANE_LABELS: Record<PulseRow["lane"], string> = {
  model: "Models",
  paper: "Papers",
  repo: "Repositories",
  news: "News",
};

export const FEEDS: Record<PulseRow["lane"], string> = {
  model: "pulse-models.xml",
  paper: "pulse-papers.xml",
  repo: "pulse-repos.xml",
  news: "pulse-news.xml",
};

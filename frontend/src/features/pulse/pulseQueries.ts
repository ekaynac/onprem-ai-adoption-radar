import { useQuery } from "@tanstack/react-query";


export type PulseRow = {
  id: string;
  lane: "model" | "paper" | "repo" | "news";
  title: string;
  url: string;
  source: string;
  published_at: string | null;
  first_seen: string;
  summary: string | null;
  kind: string | null;
  parent: string | null;
  score: number;
  bucket: "top" | "uncertain" | "hidden";
  reasons: string[];
  engine: string | null;
};

export type PulseLane = {
  lane: PulseRow["lane"];
  title: string;
  items: PulseRow[];
  uncertain: PulseRow[];
  hidden: PulseRow[];
  hidden_count: number;
  total: number;
};

export type PulseView = {
  schema_version: string;
  generated_at: string;
  lanes: PulseLane[];
  health: {
    sources: Array<{ source: string; status: string; count: number; observed_at: string }>;
    engines: Record<string, number>;
    degraded: boolean;
  };
};


/** Static site ships data/pulse.v1.json; the dev API serves the same JSON. */
export async function fetchPulse(signal?: AbortSignal): Promise<PulseView> {
  const url = import.meta.env.MODE === "static"
    ? new URL("./data/pulse.v1.json", document.baseURI).toString()
    : "/api/v1/pulse";
  const response = await fetch(url, { signal, headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new Error(`Pulse unavailable: ${response.status}`);
  }
  return response.json() as Promise<PulseView>;
}


export function usePulse() {
  return useQuery({ queryKey: ["pulse"], queryFn: ({ signal }) => fetchPulse(signal) });
}

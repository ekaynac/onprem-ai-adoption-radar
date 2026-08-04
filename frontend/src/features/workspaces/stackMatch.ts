// Accepts both the generated Workspace shape (all-optional arrays) and
// the snapshot's demo StackProfileInfo.
export type StackProfileLike = {
  devices?: Array<{ device_id?: string | null; count?: number }>;
  stack?: {
    engines?: Array<{ name: string; version?: string | null }>;
    models?: string[];
    quant_formats?: string[];
  } | null;
};


// Mirrors the backend matcher's normalization (radar.intelligence.alerts):
// engine names, model ids, quant formats, and preset device ids, casefolded.
export function profileTerms(profile: StackProfileLike): string[] {
  const terms = new Set<string>();
  for (const engine of profile.stack?.engines ?? []) {
    if (engine.name) terms.add(engine.name.toLowerCase());
  }
  for (const model of profile.stack?.models ?? []) {
    if (model) terms.add(model.toLowerCase());
  }
  for (const quant of profile.stack?.quant_formats ?? []) {
    if (quant) terms.add(quant.toLowerCase());
  }
  for (const device of profile.devices ?? []) {
    if (device.device_id) terms.add(device.device_id.toLowerCase());
  }
  return [...terms];
}


// UI-side heuristic for badging brief items: a term (or its dash-family
// root) appearing in the text counts as touching the profile's stack.
export function textTouchesProfile(text: string, terms: string[]): boolean {
  const haystack = text.toLowerCase();
  return terms.some((term) => {
    if (haystack.includes(term)) return true;
    const root = term.split("-")[0];
    return root.length >= 3 && haystack.includes(root);
  });
}

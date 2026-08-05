export function formatCount(value?: number | null): string | null {
  if (value == null || Number.isNaN(value)) return null;
  if (value >= 1e12) return `${trim(value / 1e12)}T`;
  if (value >= 1e9) return `${trim(value / 1e9)}B`;
  if (value >= 1e6) return `${trim(value / 1e6)}M`;
  if (value >= 1e3) return `${trim(value / 1e3)}K`;
  return String(value);
}

function trim(value: number): string {
  const rounded = Math.round(value * 10) / 10;
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
}

export function formatParams(
  total?: number | null,
  active?: number | null,
): string | null {
  const totalLabel = formatCount(total);
  if (!totalLabel) return null;
  const activeLabel = formatCount(active);
  // MoE models show active params: "35B A3B".
  return activeLabel && active !== total
    ? `${totalLabel} A${activeLabel}`
    : totalLabel;
}

export function formatContext(value?: number | null): string | null {
  if (value == null || value <= 0) return null;
  return value >= 1024 ? `${Math.round(value / 1024)}K` : String(value);
}


// The product's copy is English; dates render in a fixed en-US medium
// format regardless of the viewer's OS locale, so the same build shows
// (and tests assert) identical strings on every machine.
export function formatUtcDate(value?: string | null): string {
  if (!value) return "an unknown date";
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeZone: "UTC",
  }).format(new Date(value));
}

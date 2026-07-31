export type IntelligenceStatus =
  | "detected"
  | "verified"
  | "qualified"
  | "recommended"
  | "review"
  | "stale"
  | "unknown";


const labels: Record<IntelligenceStatus, string> = {
  detected: "Detected",
  verified: "Verified",
  qualified: "Qualified",
  recommended: "Recommended",
  review: "Review",
  stale: "Stale",
  unknown: "Unknown",
};


export function StatusBadge({ status }: { status: IntelligenceStatus }) {
  return (
    <span className={`status-badge status-${status}`}>
      <span className="status-dot" aria-hidden="true" />
      {labels[status]}
    </span>
  );
}

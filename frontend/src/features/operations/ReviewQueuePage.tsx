import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "../../api/client";


type ReviewException = {
  id: string;
  subject_id: string;
  code: string;
  message: string;
  evidence_ids: string[];
  opened_at: string;
  resolved_at?: string | null;
};

type LineageSuggestion = {
  id: string;
  child_release_id: string;
  parent_external_ref: string;
  parent_release_id?: string | null;
  relation: string;
  confidence: number;
};


export function ReviewQueuePage() {
  const queryClient = useQueryClient();
  const reviews = useQuery({
    queryKey: ["review-exceptions", "open"],
    queryFn: ({ signal }) =>
      apiFetch<ReviewException[]>(
        "/api/v1/operations/reviews?open_only=true",
        { signal },
      ),
  });
  const suggestions = useQuery({
    queryKey: ["lineage-suggestions"],
    queryFn: ({ signal }) =>
      apiFetch<LineageSuggestion[]>(
        "/api/v1/operations/lineage-suggestions",
        { signal },
      ),
  });
  const decide = useMutation({
    mutationFn: ({
      suggestion,
      action,
    }: {
      suggestion: LineageSuggestion;
      action: "accept" | "reject";
    }) =>
      apiFetch(
        `/api/v1/operations/lineage-suggestions/${encodeURIComponent(suggestion.id)}/${action}`,
        { method: "POST" },
      ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["lineage-suggestions"],
      });
    },
  });
  const resolve = useMutation({
    mutationFn: ({
      review,
      evidenceId,
    }: {
      review: ReviewException;
      evidenceId: string;
    }) =>
      apiFetch<ReviewException>(
        `/api/v1/operations/reviews/${encodeURIComponent(review.id)}/resolve`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            resolution: "accept_claim",
            evidence_ids: [evidenceId],
          }),
        },
      ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["review-exceptions"] });
      await queryClient.invalidateQueries({ queryKey: ["operations"] });
    },
  });

  return (
    <section className="page-stack">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Monitor · Review exceptions</p>
          <h1>Manual attention only where automation is uncertain</h1>
        </div>
      </header>
      <div className="review-list">
        {(reviews.data ?? []).map((review) => (
          <article className="panel review-card" key={review.id}>
            <div>
              <p className="eyebrow">{review.code.replaceAll("_", " ")}</p>
              <h2>{review.message}</h2>
              <p>{review.subject_id} · {review.evidence_ids.length} evidence records</p>
            </div>
            {review.code === "conflicting_authoritative_claims" ? (
              <div className="button-row">
                {review.evidence_ids.map((evidenceId, index) => (
                  <button
                    className="primary-button"
                    disabled={resolve.isPending}
                    key={evidenceId}
                    onClick={() => resolve.mutate({ review, evidenceId })}
                    type="button"
                  >
                    Accept source {index + 1}
                  </button>
                ))}
              </div>
            ) : (
              <span className="claim-reason">
                Identity exceptions require an explicit catalog merge target.
              </span>
            )}
          </article>
        ))}
        {!reviews.isLoading && !(reviews.data ?? []).length && (
          <div className="empty-state">
            <strong>No open review exceptions</strong>
            <span>Automated verification is operating within policy.</span>
          </div>
        )}
      </div>

      <section className="panel" aria-labelledby="suggestions-title">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Lineage suggestions</p>
            <h2 id="suggestions-title">
              Inferred parents awaiting confirmation
            </h2>
          </div>
        </div>
        <p className="claim-reason">
          Name-fingerprint inferences never set ancestry on their own —
          accepting one promotes it to confirmed lineage (roots and
          grouping follow); rejecting deletes the suggestion.
        </p>
        <div className="review-list">
          {(suggestions.data ?? []).map((suggestion) => (
            <article className="panel review-card" key={suggestion.id}>
              <div>
                <p className="eyebrow">
                  {suggestion.relation} · confidence {suggestion.confidence}
                </p>
                <h2>
                  {suggestion.child_release_id} →{" "}
                  {suggestion.parent_external_ref.replace(/^hf:/, "")}
                </h2>
              </div>
              <div className="button-row">
                <button
                  className="primary-button"
                  disabled={decide.isPending}
                  onClick={() => decide.mutate({ suggestion, action: "accept" })}
                  type="button"
                >
                  Confirm parent
                </button>
                <button
                  className="secondary-button"
                  disabled={decide.isPending}
                  onClick={() => decide.mutate({ suggestion, action: "reject" })}
                  type="button"
                >
                  Reject
                </button>
              </div>
            </article>
          ))}
          {!suggestions.isLoading && !(suggestions.data ?? []).length && (
            <div className="empty-state compact">
              <strong>No pending suggestions</strong>
              <span>New inferences arrive with the lineage backfill.</span>
            </div>
          )}
        </div>
      </section>
    </section>
  );
}

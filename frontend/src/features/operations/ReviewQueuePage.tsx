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
    </section>
  );
}

import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { StatusBadge, type IntelligenceStatus } from "../../design/StatusBadge";
import {
  useActiveWorkspaceId,
  usePriorityReleases,
} from "./releaseQueries";


const ALL = "all";


export function ReleaseStreamPage() {
  const workspaceId = useActiveWorkspaceId();
  const [limit, setLimit] = useState(50);
  const releases = usePriorityReleases(workspaceId, limit);
  const [lifecycle, setLifecycle] = useState(ALL);
  const [category, setCategory] = useState(ALL);
  const [lane, setLane] = useState(ALL);
  const [review, setReview] = useState(ALL);
  const [source, setSource] = useState(ALL);
  const [age, setAge] = useState<number | typeof ALL>(ALL);
  const visible = useMemo(
    () =>
      (releases.data?.items ?? []).filter(
        (item) =>
          (lifecycle === ALL || item.lifecycle === lifecycle) &&
          (category === ALL || item.category === category) &&
          (lane === ALL || item.lane === lane) &&
          (review === ALL || item.review_status === review) &&
          (source === ALL ||
            (item.citations ?? []).some(
              (citation) => citation.strength === source,
            )) &&
          (age === ALL || item.age_hours <= age),
      ),
    [age, category, lane, lifecycle, releases.data?.items, review, source],
  );

  return (
    <section className="page-stack" aria-labelledby="release-stream-title">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Intelligence · Release stream</p>
          <h1 id="release-stream-title">Every signal, with its trust state</h1>
          <p className="lede">
            Scan new model and platform changes without confusing detection
            with a recommendation.
          </p>
        </div>
      </header>
      <div className="filter-bar" aria-label="Release filters">
        <label>
          <span>Lifecycle</span>
          <select value={lifecycle} onChange={(event) => setLifecycle(event.target.value)}>
            <option value={ALL}>All states</option>
            <option value="detected">Detected</option>
            <option value="verified">Verified</option>
            <option value="qualified">Qualified</option>
            <option value="recommended">Recommended</option>
          </select>
        </label>
        <label>
          <span>Category</span>
          <select value={category} onChange={(event) => setCategory(event.target.value)}>
            <option value={ALL}>All categories</option>
            <option value="text_reasoning">Text & reasoning</option>
            <option value="multimodal">Multimodal</option>
            <option value="embedding_reranking">Embedding & reranking</option>
            <option value="speech_audio">Speech & audio</option>
            <option value="image_video">Image & video</option>
            <option value="vision_document">Vision & document</option>
          </select>
        </label>
        <label>
          <span>Lane</span>
          <select value={lane} onChange={(event) => setLane(event.target.value)}>
            <option value={ALL}>All lanes</option>
            <option value="deployable_onprem">Deployable on-prem</option>
            <option value="onprem_adjacent">On-prem adjacent</option>
            <option value="market_reference">Market reference</option>
          </select>
        </label>
        <label>
          <span>Review</span>
          <select value={review} onChange={(event) => setReview(event.target.value)}>
            <option value={ALL}>Any review state</option>
            <option value="open">Exception open</option>
            <option value="clear">Clear</option>
          </select>
        </label>
        <label>
          <span>Source</span>
          <select value={source} onChange={(event) => setSource(event.target.value)}>
            <option value={ALL}>Any source</option>
            <option value="official_artifact">Official artifact</option>
            <option value="official_repository">Official repository</option>
            <option value="trusted_registry">Trusted registry</option>
          </select>
        </label>
        <label>
          <span>Age</span>
          <select
            value={age}
            onChange={(event) =>
              setAge(
                event.target.value === ALL
                  ? ALL
                  : Number(event.target.value),
              )
            }
          >
            <option value={ALL}>All time</option>
            <option value={24}>24 hours</option>
            <option value={72}>3 days</option>
            <option value={168}>7 days</option>
          </select>
        </label>
      </div>

      {releases.isLoading ? (
        <div className="loading-grid" aria-label="Loading releases"><span /><span /></div>
      ) : releases.isError ? (
        <div className="error-state" role="alert">
          <strong>Release stream unavailable</strong>
          <button type="button" onClick={() => void releases.refetch()}>Try again</button>
        </div>
      ) : (
        <div className="release-table-wrap">
          <table className="release-table">
            <thead>
              <tr>
                <th>Release</th>
                <th>Lifecycle</th>
                <th>Lane</th>
                <th>Confidence</th>
                <th>Age</th>
                <th>Review</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((item) => (
                <tr key={item.release_id}>
                  <td>
                    <Link to={`/releases/${encodeURIComponent(item.release_id)}`}>
                      <strong>{item.name}</strong>
                      <span>{item.category.replaceAll("_", " ")}</span>
                    </Link>
                  </td>
                  <td>
                    <StatusBadge status={item.lifecycle as IntelligenceStatus} />
                  </td>
                  <td>{item.lane.replaceAll("_", " ")}</td>
                  <td>{Math.round(item.confidence * 100)}%</td>
                  <td>{item.age_hours < 1 ? "<1h" : `${Math.round(item.age_hours)}h`}</td>
                  <td>{item.review_status}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!visible.length && (
            <div className="empty-state compact">
              <strong>No releases match these filters</strong>
              <span>Broaden a filter to return more intelligence.</span>
            </div>
          )}
        </div>
      )}
      {limit < 100 && (releases.data?.items.length ?? 0) >= limit && (
        <button className="secondary-button load-more" onClick={() => setLimit(100)}>
          Load more
        </button>
      )}
      <p className="data-timestamp">Newest verified observation first</p>
    </section>
  );
}

import { useState } from "react";
import type { ObservationNode } from "./buildTree";

const KIND_ICON: Record<string, string> = {
  span: "▣",
  generation: "✦",
  tool: "⚙",
  event: "•",
};

const STATUS_LABEL: Record<string, string> = {
  running: "running",
  ok: "done",
  error: "error",
};

function formatDuration(ms?: number | null): string | null {
  if (ms == null) return null;
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

interface ObservationNodeViewProps {
  node: ObservationNode;
  depth: number;
}

/** One node in the reasoning tree: a span, tool call, generation or event,
 * expandable to reveal its children and kind-specific detail. */
export function ObservationNodeView({ node, depth }: ObservationNodeViewProps) {
  const { observation, children } = node;
  const [expanded, setExpanded] = useState(depth < 1);
  const hasDetail =
    children.length > 0 || observation.generation?.reasoning || observation.tool || observation.error;

  const duration = formatDuration(observation.duration_ms);

  return (
    <div className="observation-node" style={{ marginLeft: depth > 0 ? 16 : 0 }}>
      <button
        type="button"
        className={`observation-node__row observation-node__row--${observation.status}`}
        onClick={() => hasDetail && setExpanded((e) => !e)}
        aria-expanded={expanded}
        disabled={!hasDetail}
      >
        <span className="observation-node__toggle">{hasDetail ? (expanded ? "▾" : "▸") : " "}</span>
        <span className="observation-node__icon" aria-hidden>
          {KIND_ICON[observation.kind] ?? "•"}
        </span>
        <span className="observation-node__name">{observation.name}</span>
        <span className={`observation-node__status observation-node__status--${observation.status}`}>
          {STATUS_LABEL[observation.status] ?? observation.status}
        </span>
        {duration && <span className="observation-node__duration">{duration}</span>}
        {observation.generation?.total_tokens != null && (
          <span className="observation-node__tokens">
            {observation.generation.total_tokens} tok
          </span>
        )}
      </button>

      {expanded && (
        <div className="observation-node__detail">
          {observation.message && (
            <p className="observation-node__message">{observation.message}</p>
          )}

          {observation.error && (
            <p className="observation-node__error">Error: {observation.error}</p>
          )}

          {observation.tool && (
            <div className="observation-node__tool">
              {observation.tool.arguments && (
                <pre className="observation-node__code">
                  {JSON.stringify(observation.tool.arguments, null, 2)}
                </pre>
              )}
              {observation.tool.result_summary && (
                <p className="observation-node__result">{observation.tool.result_summary}</p>
              )}
            </div>
          )}

          {observation.generation?.reasoning && (
            <details className="observation-node__thinking">
              <summary>Thinking</summary>
              <p>{observation.generation.reasoning}</p>
            </details>
          )}

          {children.map((child) => (
            <ObservationNodeView key={child.observation.span_id} node={child} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
}

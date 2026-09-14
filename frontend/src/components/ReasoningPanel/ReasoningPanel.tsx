import { useMemo, useState } from "react";
import { buildObservationTree } from "./buildTree";
import { ObservationNodeView } from "./ObservationNodeView";
import type { Observation } from "../../types/models";

interface ReasoningPanelProps {
  observations: Map<string, Observation>;
  order: string[];
  isRunning: boolean;
}

/** The expandable "reasoning/thinking" panel: a live nested tree of the
 * agent's spans, tool calls and LLM generations. */
export function ReasoningPanel({ observations, order, isRunning }: ReasoningPanelProps) {
  const [collapsed, setCollapsed] = useState(false);
  const tree = useMemo(() => buildObservationTree(observations, order), [observations, order]);

  if (order.length === 0) return null;

  return (
    <section className="reasoning-panel">
      <button
        type="button"
        className="reasoning-panel__header"
        onClick={() => setCollapsed((c) => !c)}
        aria-expanded={!collapsed}
      >
        <span>{collapsed ? "▸" : "▾"} Agent reasoning</span>
        {isRunning && <span className="reasoning-panel__live">live</span>}
      </button>
      {!collapsed && (
        <div className="reasoning-panel__body">
          {tree.map((node) => (
            <ObservationNodeView key={node.observation.span_id} node={node} depth={0} />
          ))}
        </div>
      )}
    </section>
  );
}

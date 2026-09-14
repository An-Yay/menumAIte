import type { Observation } from "../../types/models";

export interface ObservationNode {
  observation: Observation;
  children: ObservationNode[];
}

/**
 * Rebuilds the nested tree from a flat map of observations keyed by span_id,
 * using `parent_span_id` the way an OpenTelemetry-aware viewer would. Order
 * is preserved via `order` (insertion order of first-seen span ids) so
 * siblings render in the sequence the agent actually started them.
 */
export function buildObservationTree(
  observations: Map<string, Observation>,
  order: string[],
): ObservationNode[] {
  const nodes = new Map<string, ObservationNode>();
  for (const spanId of order) {
    const observation = observations.get(spanId);
    if (observation) nodes.set(spanId, { observation, children: [] });
  }

  const roots: ObservationNode[] = [];
  for (const spanId of order) {
    const node = nodes.get(spanId);
    if (!node) continue;
    const parentId = node.observation.parent_span_id;
    const parent = parentId ? nodes.get(parentId) : undefined;
    if (parent) {
      parent.children.push(node);
    } else {
      roots.push(node);
    }
  }

  return roots;
}

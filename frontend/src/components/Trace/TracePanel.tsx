/**
 * A toggle-able left-column trace of the agent's work.
 *
 * A raw, OpenTelemetry-style view of every span and generation across the whole
 * conversation: the tool calls with their timings and status, and the model calls
 * with their token counts and estimated cost. It sits apart from the friendly
 * in-turn reasoning panel and is aimed at inspecting what the agent did and what
 * it cost, so it is off by default and revealed with a toggle.
 */

import { useMemo } from "react";
import type { Turn } from "../../hooks/useConversation";
import type { GenerationRecord, Observation } from "../../types/models";

interface TracePanelProps {
  turns: Turn[];
  onClose: () => void;
}

function formatDuration(ms?: number | null): string {
  if (ms == null) return "";
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s`;
}

function formatCost(usd?: number | null): string {
  if (usd == null) return "—";
  // Sub-cent costs would round to $0.00, so show more precision when small.
  return usd < 0.01 ? `$${usd.toFixed(5)}` : `$${usd.toFixed(4)}`;
}

export function TracePanel({ turns, onClose }: TracePanelProps) {
  const assistantTurns = turns.filter((t) => t.role === "assistant");

  const totalCost = useMemo(
    () => assistantTurns.reduce((sum, t) => sum + t.costUsd, 0),
    [assistantTurns],
  );

  return (
    <aside className="trace-panel" aria-label="Agent trace">
      <div className="trace-panel__header">
        <span>Trace</span>
        <button
          type="button"
          className="trace-panel__close"
          onClick={onClose}
          aria-label="Hide trace"
        >
          ×
        </button>
      </div>

      <div className="trace-panel__summary">
        Session estimated cost <strong>{formatCost(totalCost)}</strong>
      </div>

      <div className="trace-panel__body">
        {assistantTurns.length === 0 && (
          <p className="trace-panel__empty">No activity yet.</p>
        )}

        {assistantTurns.map((turn, i) => (
          <section key={turn.id} className="trace-turn">
            <h4 className="trace-turn__title">
              Turn {i + 1}
              <span className="trace-turn__cost">{formatCost(turn.costUsd)}</span>
            </h4>

            {/* Spans: tool calls and the root, in the order they happened. */}
            {turn.observationOrder.map((spanId) => {
              const obs = turn.observations.get(spanId) as Observation | undefined;
              if (!obs) return null;
              return (
                <div key={spanId} className={`trace-span trace-span--${obs.status}`}>
                  <span className="trace-span__kind">{obs.kind}</span>
                  <span className="trace-span__name">{obs.name}</span>
                  <span className="trace-span__meta">
                    {obs.status}
                    {obs.duration_ms != null && ` · ${formatDuration(obs.duration_ms)}`}
                  </span>
                </div>
              );
            })}

            {/* Generations: model calls with tokens and cost. */}
            {turn.generations.map((gen: GenerationRecord, j) => (
              <div key={j} className="trace-gen">
                <span className="trace-gen__kind">generation</span>
                <span className="trace-gen__name">{gen.label}</span>
                <span className="trace-gen__meta">
                  {gen.input_tokens}→{gen.output_tokens} tok · {formatCost(gen.cost_usd)}
                </span>
              </div>
            ))}
          </section>
        ))}
      </div>
    </aside>
  );
}

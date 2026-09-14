/**
 * Renders the agent's reply.
 *
 * The backend streams the reply as light markdown (headings, bold, links, bullet
 * points). Rather than pull in a markdown library and its `dangerouslySetInnerHTML`
 * surface, this renders the small subset the agent actually produces as safe React
 * elements. Anything it does not recognise is shown as plain text, so unexpected
 * markup degrades to something readable rather than breaking.
 */

import type { ReactNode } from "react";

interface AgentReplyProps {
  text: string;
}

// Matches **bold** and [label](url) so inline formatting can be rendered without
// interpreting the whole string as HTML.
const INLINE = /(\*\*[^*]+\*\*)|(\[[^\]]+\]\([^)]+\))/g;

function renderInline(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let lastIndex = 0;
  let key = 0;

  for (const match of text.matchAll(INLINE)) {
    const token = match[0];
    const start = match.index ?? 0;

    if (start > lastIndex) {
      nodes.push(text.slice(lastIndex, start));
    }

    if (token.startsWith("**")) {
      nodes.push(<strong key={key++}>{token.slice(2, -2)}</strong>);
    } else {
      // A markdown link: [label](url).
      const label = token.slice(1, token.indexOf("]"));
      const url = token.slice(token.indexOf("(") + 1, -1);
      nodes.push(
        <a key={key++} href={url} target="_blank" rel="noreferrer noopener">
          {label}
        </a>,
      );
    }

    lastIndex = start + token.length;
  }

  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex));
  }

  return nodes;
}

export function AgentReply({ text }: AgentReplyProps) {
  // Split into blocks on blank lines, then render each block by its leading marker.
  const blocks = text.split(/\n{2,}/);

  return (
    <div className="agent-reply">
      {blocks.map((block, i) => {
        const trimmed = block.trim();
        if (!trimmed) return null;

        // Headings: one or more leading '#'.
        const heading = trimmed.match(/^(#{1,6})\s+(.*)$/);
        if (heading) {
          return (
            <h3 key={i} className="agent-reply__heading">
              {renderInline(heading[2])}
            </h3>
          );
        }

        // A run of list items ('-' or '1.') becomes a list.
        const lines = trimmed.split("\n");
        const isList = lines.every((line) => /^\s*([-*]|\d+\.)\s+/.test(line));
        if (isList) {
          return (
            <ul key={i} className="agent-reply__list">
              {lines.map((line, j) => (
                <li key={j}>{renderInline(line.replace(/^\s*([-*]|\d+\.)\s+/, ""))}</li>
              ))}
            </ul>
          );
        }

        // Otherwise a paragraph; keep single line breaks within it.
        return (
          <p key={i} className="agent-reply__paragraph">
            {lines.map((line, j) => (
              <span key={j}>
                {renderInline(line)}
                {j < lines.length - 1 && <br />}
              </span>
            ))}
          </p>
        );
      })}
    </div>
  );
}

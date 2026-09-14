"""Translate Strands stream events into the interface's event format.

Strands emits a fine-grained stream describing its internal event loop. The
interface needs something coarser and more meaningful: which pipeline step is
running, which tool was called with what, and the assistant's text as it arrives.

This module is that translation layer. Keeping it separate from the HTTP endpoint
means the mapping can be tested on recorded events, and means a change in the
SDK's event shape only affects one file.

Emitted event types
-------------------
``observation``
    A node in the reasoning tree, matching the `Observation` model. Rendered as
    the expandable "how it worked" panel.
``text``
    An incremental chunk of the assistant's reply, for typing-style output.
``final``
    The complete assistant reply.
``error``
    Something failed; carries a human-readable message.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Iterator

from app.models import (
    Observation,
    ObservationKind,
    ObservationStatus,
    PipelineStep,
    ToolMetadata,
)

# Maps each tool onto the pipeline step it represents, so the interface can group
# and label the reasoning tree in product terms rather than tool names.
_TOOL_STEPS: dict[str, PipelineStep] = {
    "resolve_dietary_profile": PipelineStep.INTAKE,
    "discover_restaurants": PipelineStep.DISCOVER,
    "read_menu": PipelineStep.FETCH_MENU,
    "extract_menu_items": PipelineStep.TRANSLATE_MENU,
    "get_restaurant_reviews": PipelineStep.ANALYSE_REVIEWS,
    "analyse_restaurant_reviews": PipelineStep.CONTEXT_REVIEW_SEARCH,
    "search_menu_online": PipelineStep.FETCH_MENU,
}

# Short, human-readable descriptions shown while each tool runs.
_TOOL_MESSAGES: dict[str, str] = {
    "resolve_dietary_profile": "Working out what these dietary needs mean",
    "discover_restaurants": "Searching for restaurants",
    "read_menu": "Reading the menu from the restaurant's website",
    "extract_menu_items": "Extracting and translating menu items",
    "get_restaurant_reviews": "Fetching reviews",
    "analyse_restaurant_reviews": "Reading the positive and negative reviews",
    "search_menu_online": "Searching the web for a menu the website did not provide",
}


def _now() -> str:
    """Current UTC time as an ISO-8601 string."""

    return datetime.now(timezone.utc).isoformat()


class EventTranslator:
    """Converts a Strands event stream into interface events.

    Holds the small amount of state needed to correlate events: the trace id for
    the run, and which tool calls have already been announced. Strands emits many
    partial events per tool call as the arguments stream in, and the interface only
    needs to be told about each call once.
    """

    def __init__(self) -> None:
        self.trace_id = uuid.uuid4().hex
        # Root span that every observation hangs from, giving the interface a tree
        # rather than a flat list.
        self.root_span_id = uuid.uuid4().hex
        self._announced_tools: set[str] = set()
        self._completed_tools: set[str] = set()

    def start(self) -> dict[str, Any]:
        """The opening observation for a run."""

        return self._observation(
            Observation(
                span_id=self.root_span_id,
                trace_id=self.trace_id,
                kind=ObservationKind.SPAN,
                name="recommend_restaurants",
                message="Working on your request",
                status=ObservationStatus.RUNNING,
                started_at=_now(),
            )
        )

    def translate(self, event: dict[str, Any]) -> Iterator[dict[str, Any]]:
        """Yield zero or more interface events for one Strands event."""

        if not isinstance(event, dict):
            return

        # A tool call, still streaming its arguments. Announced once, when first
        # seen, so the interface can show the step immediately rather than waiting
        # for the arguments to finish arriving.
        tool_use = event.get("current_tool_use")
        if isinstance(tool_use, dict):
            tool_id = tool_use.get("toolUseId")
            name = tool_use.get("name")
            if tool_id and name and tool_id not in self._announced_tools:
                self._announced_tools.add(tool_id)
                yield self._observation(
                    Observation(
                        span_id=tool_id,
                        trace_id=self.trace_id,
                        parent_span_id=self.root_span_id,
                        kind=ObservationKind.TOOL,
                        name=name,
                        step=_TOOL_STEPS.get(name),
                        message=_TOOL_MESSAGES.get(name, f"Running {name}"),
                        status=ObservationStatus.RUNNING,
                        started_at=_now(),
                        tool=ToolMetadata(tool_name=name),
                    )
                )

        # A completed message. When it contains a tool use, the arguments are now
        # fully parsed, so the tool observation can be completed with them.
        message = event.get("message")
        if isinstance(message, dict):
            for block in message.get("content", []) or []:
                if not isinstance(block, dict):
                    continue
                completed = block.get("toolUse")
                if not isinstance(completed, dict):
                    continue

                tool_id = completed.get("toolUseId")
                name = completed.get("name")
                if not tool_id or tool_id in self._completed_tools:
                    continue
                self._completed_tools.add(tool_id)

                arguments = completed.get("input")
                yield self._observation(
                    Observation(
                        span_id=tool_id,
                        trace_id=self.trace_id,
                        parent_span_id=self.root_span_id,
                        kind=ObservationKind.TOOL,
                        name=name or "tool",
                        step=_TOOL_STEPS.get(name or ""),
                        message=_TOOL_MESSAGES.get(name or "", f"Ran {name}"),
                        status=ObservationStatus.OK,
                        ended_at=_now(),
                        tool=ToolMetadata(
                            tool_name=name or "tool",
                            arguments=arguments if isinstance(arguments, dict) else None,
                        ),
                    )
                )

        # Incremental assistant text.
        data = event.get("data")
        if isinstance(data, str) and data:
            yield {"type": "text", "text": data}

        # The finished reply.
        if "result" in event:
            yield {
                "type": "final",
                "text": str(event["result"]),
                "trace_id": self.trace_id,
            }

    def finish(self) -> dict[str, Any]:
        """The closing observation for a run."""

        return self._observation(
            Observation(
                span_id=self.root_span_id,
                trace_id=self.trace_id,
                kind=ObservationKind.SPAN,
                name="recommend_restaurants",
                message="Done",
                status=ObservationStatus.OK,
                ended_at=_now(),
            )
        )

    def error(self, message: str) -> dict[str, Any]:
        """An error event for the interface to surface."""

        return {"type": "error", "message": message, "trace_id": self.trace_id}

    @staticmethod
    def _observation(observation: Observation) -> dict[str, Any]:
        """Wrap an `Observation` as an interface event."""

        return {"type": "observation", "observation": observation.model_dump(mode="json")}

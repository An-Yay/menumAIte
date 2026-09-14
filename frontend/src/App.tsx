import { useState } from "react";
import { Conversation } from "./components/Chat/Conversation";
import { TracePanel } from "./components/Trace/TracePanel";
import { useConversation } from "./hooks/useConversation";
import "./App.css";

/**
 * Application shell.
 *
 * The main experience is the conversation. The trace panel is an optional
 * left-column view of the agent's spans, generations and cost; it is off by
 * default so it never competes with the conversation, and toggled from the
 * header.
 */
function App() {
  const conversation = useConversation();
  const [showTrace, setShowTrace] = useState(false);

  return (
    <div className={`app${showTrace ? " app--with-trace" : ""}`}>
      {showTrace && (
        <TracePanel turns={conversation.turns} onClose={() => setShowTrace(false)} />
      )}

      <div className="app__column">
        <header className="app__header">
          <div>
            <h1>menumAIte</h1>
            <p>Find somewhere to eat, wherever you are.</p>
          </div>
          <button
            type="button"
            className="app__trace-toggle"
            onClick={() => setShowTrace((v) => !v)}
            aria-pressed={showTrace}
          >
            {showTrace ? "Hide trace" : "Trace"}
          </button>
        </header>

        <main className="app__main">
          <Conversation conversation={conversation} />
        </main>
      </div>
    </div>
  );
}

export default App;

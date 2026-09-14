import { IntakeChat } from "./components/Chat/IntakeChat";
import { ReasoningPanel } from "./components/ReasoningPanel/ReasoningPanel";
import { ResultsList } from "./components/Results/ResultsList";
import { useAgentStream } from "./hooks/useAgentStream";
import type { SearchBrief } from "./types/models";
import "./App.css";

function App() {
  const { status, observations, order, suggestions, errorMessage, start, reset } =
    useAgentStream();

  function handleConfirm(brief: SearchBrief) {
    void start(brief);
  }

  const isIntakeVisible = status === "idle";

  return (
    <div className="app">
      <header className="app__header">
        <h1>menumAIte</h1>
        <p>Find somewhere to eat, wherever you are.</p>
      </header>

      <main className="app__main">
        {isIntakeVisible && <IntakeChat onConfirm={handleConfirm} />}

        {!isIntakeVisible && (
          <>
            <button type="button" className="app__restart" onClick={reset}>
              ← New search
            </button>

            <ReasoningPanel
              observations={observations}
              order={order}
              isRunning={status === "running"}
            />

            {status === "running" && suggestions === null && (
              <p className="app__status">Working on it…</p>
            )}

            {status === "error" && (
              <p className="app__error">Something went wrong: {errorMessage}</p>
            )}

            {suggestions && <ResultsList suggestions={suggestions} />}
          </>
        )}
      </main>
    </div>
  );
}

export default App;

import { Conversation } from "./components/Chat/Conversation";
import "./App.css";

/**
 * Application shell.
 *
 * The whole experience is one conversation, so the shell is just a header and the
 * conversation itself. State lives in `useConversation`, alongside the streaming
 * that drives it.
 */
function App() {
  return (
    <div className="app">
      <header className="app__header">
        <h1>menumAIte</h1>
        <p>Find somewhere to eat, wherever you are.</p>
      </header>

      <main className="app__main">
        <Conversation />
      </main>
    </div>
  );
}

export default App;

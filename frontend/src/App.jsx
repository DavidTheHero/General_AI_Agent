import { useEffect, useRef, useState } from "react";
import FinanceWorkspace from "./FinanceWorkspace.jsx";
import FinanceReport from "./FinanceReport.jsx";
import TradingDashboard from "./TradingDashboard.jsx";

function initialConversation() {
    try {
        const saved = JSON.parse(sessionStorage.getItem("assistant-conversation"));
        if (saved?.session_id && Array.isArray(saved.messages) && saved.metadata) return saved;
    } catch { /* Start a fresh conversation if browser storage is unavailable or invalid. */ }
    return { session_id: crypto.randomUUID(), metadata: {}, messages: [] };
}

async function post(path, body) {
    const response = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || data.error || "Request failed.");
    return data;
}

function AssistantMessage({ message }) {
    if (message.error) return <p className="error" role="alert">{message.error}</p>;
    const raw = message.raw;
    return <>
        {raw.responses?.length ? raw.responses.map((response, index) => response.report ? <FinanceReport key={index} report={response.report} /> : <div key={index}><p>{response.answer}</p>{response.trading_job && <a href={`/?trading_job=${encodeURIComponent(response.trading_job.id)}`}>Open trading dashboard</a>}</div>) : <p>{raw.answer}</p>}
        <div className="meta-row">
            Tools: {Object.keys(raw.usage || {}).join(", ") || "none"}
            <span className="latency-chip">{Math.round(raw.latency_ms || 0)} ms</span>
            <details><summary>Timings</summary><ul>
                {Object.entries(raw.timings || {}).map(([name, stats]) => <li key={name}>{name}: {stats.avg_ms.toFixed(1)} ms ({stats.count}×)</li>)}
            </ul></details>
            {raw.metadata?.agent_trace && <details><summary>Agent actions</summary><pre>{JSON.stringify(raw.metadata.agent_trace, null, 2)}</pre></details>}
            {raw.metadata?.plan_trace && <details><summary>Plan</summary><pre>{JSON.stringify(raw.metadata.plan_trace, null, 2)}</pre></details>}
            <details><summary>Token estimates</summary><pre>{JSON.stringify(raw.token_usage || {}, null, 2)}</pre></details>
        </div>
    </>;
}

export default function App() {
    const [view, setView] = useState(() => new URLSearchParams(window.location.search).has("trading_job") ? "trading" : "chat");
    const [conversation, setConversation] = useState(initialConversation);
    const [query, setQuery] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    const [online, setOnline] = useState(null);
    const chatBox = useRef(null), input = useRef(null);
    useEffect(() => {
        fetch("/health").then((response) => setOnline(response.ok)).catch(() => setOnline(false));
    }, []);
    useEffect(() => {
        try { sessionStorage.setItem("assistant-conversation", JSON.stringify(conversation)); } catch { /* Chat works without storage. */ }
        chatBox.current?.scrollTo?.({ top: chatBox.current.scrollHeight });
    }, [conversation, busy]);

    async function send(event) {
        event.preventDefault();
        const text = query.trim();
        if (!text || busy) return;
        setBusy(true);
        setError("");
        setQuery("");
        setConversation((state) => ({ ...state, messages: [...state.messages, { role: "user", text }] }));
        try {
            const raw = await post("/query", { query: text, metadata: { ...conversation.metadata, session_id: conversation.session_id } });
            const { semantic_matches, timings, plan_trace, ...metadata } = raw.metadata || {};
            setConversation((state) => ({ ...state, metadata, messages: [...state.messages, { role: "assistant", raw }] }));
            setOnline(true);
        } catch (failure) {
            setConversation((state) => ({ ...state, messages: [...state.messages, { role: "assistant", error: failure.message }] }));
        } finally {
            setBusy(false);
            input.current?.focus();
        }
    }

    async function reset() {
        if (busy) return;
        setBusy(true);
        setError("");
        try {
            await post("/memory/reset", { session_id: conversation.session_id });
            setConversation({ session_id: crypto.randomUUID(), metadata: {}, messages: [] });
        } catch (failure) { setError(failure.message); }
        finally { setBusy(false); }
    }

    return <main className={`app-shell ${view !== "chat" ? "workspace-shell" : ""}`}>
        <header>
            <div className="brand"><span className="brand-mark" aria-hidden="true">a.</span><div><h1>Assistant Agent</h1><small className="subtitle">Your research, connected.</small></div></div>
            <span className={`status-pill ${online === false ? "offline" : ""}`}>{online === null ? "Connecting" : online ? "Connected" : "Offline"}</span>
        </header>
        <nav className="app-navigation" aria-label="Application views"><button type="button" aria-pressed={view === "chat"} onClick={() => setView("chat")}>Chat</button><button type="button" aria-pressed={view === "finance"} onClick={() => setView("finance")}>Finance workspace</button><button type="button" aria-pressed={view === "trading"} onClick={() => setView("trading")}>Trading desk</button></nav>
        {view === "trading" && <div className="workspace-container"><TradingDashboard initialJob={new URLSearchParams(window.location.search).get("trading_job") || ""} /></div>}
        <div hidden={view !== "finance"} className="workspace-container"><FinanceWorkspace onChat={(text) => { setQuery(text); setView("chat"); input.current?.focus(); }} /></div>
        <div hidden={view !== "chat"} className="chat-view">
        <div className="chat-box" ref={chatBox} role="log" aria-label="Conversation" aria-live="polite">
            {!conversation.messages.length && <div className="chat-welcome"><span className="eyebrow">YOUR RESEARCH COMPANION</span><h2>Start with a question.<br />Follow the evidence.</h2><p>Explore markets, research companies, or ask about your day.</p><div className="starter-prompts">{["Give me a company research brief on Nvidia", "How is the stock market today?", "What is the weather in London?"].map((text) => <button type="button" key={text} onClick={() => { setQuery(text); input.current?.focus(); }}>{text}<span aria-hidden="true">↗</span></button>)}</div></div>}
            {conversation.messages.map((message, index) => <div key={index} className={`message ${message.role}`}>
                <strong>{message.role === "user" ? "You" : "Assistant"}</strong>
                {message.role === "user" ? <p>{message.text}</p> : <AssistantMessage message={message} />}
            </div>)}
            {busy && <div className="message assistant pending" role="status">Working…</div>}
        </div>
        <div className="composer">
            {error && <p className="error" role="alert">{error}</p>}
            <form onSubmit={send}>
                <label htmlFor="query-input" className="sr-only">Message</label>
                <textarea id="query-input" ref={input} value={query} onChange={(event) => setQuery(event.target.value)}
                    placeholder="Type your message here..." onKeyDown={(event) => {
                        if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); send(event); }
                    }} />
                <div className="actions"><div className="button-row">
                    <button className="primary-btn" disabled={busy || !query.trim()}>Send</button>
                    <button type="button" className="ghost-btn" onClick={reset} disabled={busy}>Reset conversation</button>
                </div><small className="meta">Enter to send · Shift+Enter for a new line</small></div>
            </form>
        </div>
        </div>
    </main>;
}

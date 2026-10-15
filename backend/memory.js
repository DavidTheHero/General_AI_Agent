import { createHash } from "node:crypto";
import { DatabaseSync } from "node:sqlite";

export function defaultMemory() {
    return {
        conversation_context: { last_query: "", last_effective_query: "", last_tool: "" },
        stock_context: { last_quote: null, last_comparison: null, comparison_history: [], recent_symbols: [] },
        weather_context: { last_location: null, last_conditions: null, last_updated: null },
        fact_context: { recent_facts: [] },
        time_context: { last_timezone_request: null, last_time_result: null, last_conversion: null },
        user_profile: { reminders: [] },
    };
}

export function createMemory(initial = {}) {
    const memory = defaultMemory();
    for (const key of Object.keys(memory)) {
        memory[key] = { ...memory[key], ...structuredClone(initial[key] || {}) };
    }
    return memory;
}

export function rememberSymbols(memory, symbols) {
    let recent = memory.stock_context.recent_symbols;
    for (const symbol of symbols) {
        recent = [...recent.filter((item) => item !== symbol), symbol];
    }
    memory.stock_context.recent_symbols = recent.slice(-8);
}

export function rememberComparison(memory, entries, days) {
    const record = {
        entries, days, timestamp: new Date().toISOString(), symbols: entries.map((entry) => entry.symbol),
    };
    memory.stock_context.last_comparison = record;
    memory.stock_context.comparison_history = [...memory.stock_context.comparison_history, record].slice(-5);
    rememberSymbols(memory, record.symbols);
}

function embed(text) {
    const vector = Array(256).fill(0);
    for (const token of text.toLowerCase().match(/[a-z0-9']+/g) || []) {
        const normalized = token.replace(/^'+|'+$/g, "");
        if (normalized) vector[createHash("sha256").update(normalized).digest().readUInt32BE(0) % 256]++;
    }
    return vector;
}

function similarity(a, b) {
    const dot = a.reduce((sum, value, i) => sum + value * b[i], 0);
    const norm = Math.hypot(...a) * Math.hypot(...b);
    return norm ? dot / norm : 0;
}

export class SemanticMemoryStore {
    constructor(path = process.env.SEMANTIC_DB_PATH || "semantic_memory.db") {
        this.db = new DatabaseSync(path);
        this.db.exec(`
            CREATE TABLE IF NOT EXISTS semantic_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL,
                metadata TEXT, embedding TEXT NOT NULL, created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_semantic_session
                ON semantic_memory(session_id, created_at DESC);
        `);
    }

    addEntry(session, role, content, metadata = {}) {
        if (!content.trim()) return;
        this.db.prepare(`INSERT INTO semantic_memory
            (session_id, role, content, metadata, embedding, created_at) VALUES (?, ?, ?, ?, ?, ?)`)
            .run(session, role, content, JSON.stringify(metadata), JSON.stringify(embed(content)), Date.now() / 1000);
    }

    query(session, text, topK = 3) {
        if (!text.trim()) return [];
        const vector = embed(text);
        return this.db.prepare(`SELECT * FROM semantic_memory WHERE session_id = ?
            ORDER BY created_at DESC, id DESC LIMIT 200`).all(session)
            .map((row) => ({
                id: row.id, session_id: row.session_id, role: row.role, content: row.content,
                metadata: JSON.parse(row.metadata || "{}"), timestamp: row.created_at,
                // Re-embed content so existing Python rows use the same deterministic hash.
                score: similarity(vector, embed(row.content)),
            }))
            .filter((row) => row.score >= 0.15)
            .sort((a, b) => b.score - a.score).slice(0, topK);
    }

    deleteSession(session) {
        this.db.prepare("DELETE FROM semantic_memory WHERE session_id = ?").run(session);
    }

    recent(session, limit = 4) {
        return this.db.prepare("SELECT role, content FROM semantic_memory WHERE session_id = ? ORDER BY id DESC LIMIT ?")
            .all(session, limit).reverse();
    }

    close() {
        this.db.close();
    }
}

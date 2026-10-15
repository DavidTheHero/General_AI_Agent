import test from "node:test";
import assert from "node:assert/strict";
import request from "supertest";
import { createApp } from "../app.js";
import { createAgent } from "../agent.js";
import { SemanticMemoryStore } from "../memory.js";

function setup(t) {
    const store = new SemanticMemoryStore(":memory:");
    t.after(() => store.close());
    const agent = createAgent({ store, chains: { router: { invoke: async () => ({ tool_choice: "none", direct_answer: "Hello" }) } } });
    return { store, app: createApp({ agent, store, frontendPath: "/nonexistent" }) };
}

test("health and query retain the API response contract", async (t) => {
    const { app } = setup(t);
    await request(app).get("/health").expect(200, { status: "ok" });
    const result = await request(app).post("/query").send({ query: "Hello", metadata: { session_id: "a" } }).expect(200);
    assert.equal(result.body.metadata.session_id, "a");
    assert.ok(result.body.responses.length);
    assert.equal(typeof result.body.latency_ms, "number");
});

test("invalid payloads receive 400 responses", async (t) => {
    const { app } = setup(t);
    for (const body of [{}, { query: " " }, { query: 12 }, { query: "Hello", metadata: [] }, { query: "Hello", metadata: { stock_context: { recent_symbols: "invalid" } } }]) {
        await request(app).post("/query").send(body).expect(400);
    }
    await request(app).post("/query").set("Content-Type", "application/json").send("{invalid").expect(400);
    await request(app).post("/memory/search").send({ session_id: "a", query: "test", top_k: -1 }).expect(400);
    await request(app).post("/memory/reset").send({ session_id: 12 }).expect(400);
});

test("search and reset cannot read or delete another session", async (t) => {
    const { app, store } = setup(t);
    store.addEntry("a", "user", "Paris travel");
    store.addEntry("b", "user", "Paris travel");
    const search = await request(app).post("/memory/search").send({ session_id: "a", query: "Paris" }).expect(200);
    assert.equal(search.body.matches.length, 1);
    assert.equal(search.body.matches[0].session_id, "a");
    await request(app).post("/memory/reset").send({ session_id: "a" }).expect(200);
    assert.equal(store.query("a", "Paris").length, 0);
    assert.equal(store.query("b", "Paris").length, 1);
});

test("backend model errors return a useful JSON error", async (t) => {
    const { store } = setup(t);
    const app = createApp({ store, agent: { run: async () => { throw new Error("Ollama unavailable"); } }, frontendPath: "/nonexistent" });
    const result = await request(app).post("/query").send({ query: "Hello" }).expect(500);
    assert.equal(result.body.detail, "Ollama unavailable");
});

test("nullable legacy metadata and reset without a session remain supported", async (t) => {
    const { app, store } = setup(t);
    store.addEntry("a", "user", "Paris");
    await request(app).post("/query").send({ query: "Hello", metadata: null }).expect(200);
    const reset = await request(app).post("/memory/reset").send({}).expect(200);
    assert.equal(reset.body.session_id, null);
    assert.equal(store.query("a", "Paris").length, 1);
});

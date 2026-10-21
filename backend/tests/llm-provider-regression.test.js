import test from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { once } from "node:events";
import { createModel, createChains } from "../llm.js";

async function startServer(t, handler) {
    const requests = [];
    const server = createServer((request, response) => {
        let body = "";
        request.on("data", (chunk) => { body += chunk; });
        request.on("end", () => {
            try {
                requests.push({ path: request.url, authorization: request.headers.authorization, body: body ? JSON.parse(body) : null });
                handler(request, response, requests);
            } catch (error) {
                if (!response.headersSent) {
                    response.writeHead(500, { "content-type": "application/json" });
                }
                response.end(JSON.stringify({ error: { message: String(error && error.message || error), type: "internal_error" } }));
            }
        });
    });
    server.listen(0, "127.0.0.1");
    t.after(() => new Promise((resolve, reject) => {
        server.close((error) => error ? reject(error) : resolve());
        server.closeAllConnections();
    }));
    await once(server, "listening");
    return { server, requests };
}

function vllmModel(server, ollamaServer) {
    return createModel({ env: {
        LLM_PROVIDER: "vllm", VLLM_MODEL: "local-model",
        VLLM_BASE_URL: `http://127.0.0.1:${server.address().port}/v1`,
        VLLM_API_KEY: "test-local-key",
        OLLAMA_HOST: `http://127.0.0.1:${ollamaServer.server.address().port}`,
        OLLAMA_MODEL: "ollama-local-model",
    } });
}

function completionEnvelope(content) {
    return JSON.stringify({
        id: "local-test", object: "chat.completion", created: 0, model: "local-model",
        choices: [{ index: 0, message: { role: "assistant", content }, finish_reason: "stop" }],
        usage: { prompt_tokens: 10, completion_tokens: 5, total_tokens: 15 },
    });
}

test("malformed completion JSON inside a valid chat.completion envelope rejects as a structured output parser failure", { timeout: 15000 }, async (t) => {
    const badContent = "{ this is not valid json";
    const { server, requests } = await startServer(t, (request, response) => {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(completionEnvelope(badContent));
    });
    const ollamaServer = await startServer(t, (request, response) => {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ model: "ollama-local-model", message: { role: "assistant", content: "ollama-should-not-be-called" } }));
    });
    const model = vllmModel(server, ollamaServer);
    await assert.rejects(createChains(model).general.invoke({ query: "Hello" }, { signal: AbortSignal.timeout(10000) }), (error) => {
        assert.ok(error instanceof SyntaxError, `Expected SyntaxError, got ${error.constructor.name}: ${error.message}`);
        assert.match(error.message, /invalid structured output JSON/i);
        return true;
    });
    t.diagnostic(`malformed-JSON vLLM request count: ${requests.length}`);
    assert.equal(requests.length, 2);
    assert.equal(requests[0].path, "/v1/chat/completions");
    assert.equal(requests[1].path, "/v1/chat/completions");
    assert.equal(ollamaServer.requests.length, 0);
});

test("missing required answer field in a valid chat.completion envelope is rejected by local Zod validation", { timeout: 15000 }, async (t) => {
    const { server, requests } = await startServer(t, (request, response) => {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(completionEnvelope(JSON.stringify({ not_answer: "value" })));
    });
    const ollamaServer = await startServer(t, (request, response) => {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ model: "ollama-local-model", message: { role: "assistant", content: "ollama-should-not-be-called" } }));
    });
    const model = vllmModel(server, ollamaServer);
    await assert.rejects(createChains(model).general.invoke({ query: "Hello" }, { signal: AbortSignal.timeout(10000) }), (error) => {
        assert.ok(error.issues, `Expected Zod error with issues, got ${error.constructor.name}: ${error.message}`);
        const answerIssue = error.issues.find((issue) => issue.path[0] === "answer");
        assert.ok(answerIssue, `Expected an issue for 'answer', got issues: ${JSON.stringify(error.issues)}`);
        assert.equal(answerIssue.code, "invalid_type");
        return true;
    });
    assert.equal(requests.length, 1);
    assert.equal(requests[0].path, "/v1/chat/completions");
    assert.equal(ollamaServer.requests.length, 0);
});

test("loop response selecting a tool outside allowed_tools is rejected by local Zod validation even when HTTP returns 200", { timeout: 15000 }, async (t) => {
    const { server, requests } = await startServer(t, (request, response) => {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(completionEnvelope(JSON.stringify({ action: "tool", tool: "weather", arguments: { location: "London" }, message: "" })));
    });
    const ollamaServer = await startServer(t, (request, response) => {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ model: "ollama-local-model", message: { role: "assistant", content: "ollama-should-not-be-called" } }));
    });
    const model = vllmModel(server, ollamaServer);
    await assert.rejects(createChains(model).loop.invoke({
        query: "Weather in London", context: "{}", reference_date: "2026-10-17", timezone: "Europe/London",
        allowed_tools: ["calculator"], available_tools: "calculator", observations: "[]", remaining_steps: 1,
    }, { signal: AbortSignal.timeout(10000) }), (error) => {
        assert.ok(error.issues, `Expected Zod error with issues, got ${error.constructor.name}: ${error.message}`);
        const toolIssue = error.issues.find((issue) => issue.path[0] === "tool");
        assert.ok(toolIssue, `Expected an issue for 'tool', got issues: ${JSON.stringify(error.issues)}`);
        assert.equal(toolIssue.code, "invalid_value");
        assert.deepEqual(toolIssue.values, ["", "calculator"]);
        return true;
    });
    assert.equal(requests.length, 1);
    assert.equal(requests[0].path, "/v1/chat/completions");
    assert.equal(ollamaServer.requests.length, 0);
});

test("workspace structured output applies local normalization: lowercase symbol becomes uppercase with workflow preserved", { timeout: 15000 }, async (t) => {
    const { server, requests } = await startServer(t, (request, response) => {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(completionEnvelope(JSON.stringify({ request: { workflow: "research", symbol: "nvda" }, clarification: "" })));
    });
    const ollamaServer = await startServer(t, (request, response) => {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ model: "ollama-local-model", message: { role: "assistant", content: "ollama-should-not-be-called" } }));
    });
    const model = vllmModel(server, ollamaServer);
    const result = await createChains(model).workspace.invoke({ query: "Research Nvidia", reference_date: "2026-10-17", timezone: "Europe/London" }, { signal: AbortSignal.timeout(10000) });
    assert.equal(result.request.workflow, "research");
    assert.equal(result.request.symbol, "NVDA");
    assert.equal(result.clarification, "");
    assert.equal(requests.length, 1);
    assert.equal(requests[0].path, "/v1/chat/completions");
    assert.equal(ollamaServer.requests.length, 0);
});

test("HTTP 503 surfaces an error after a finite retry sequence without switching to Ollama", { timeout: 15000 }, async (t) => {
    const { server, requests } = await startServer(t, (request, response) => {
        response.writeHead(503, { "content-type": "application/json" });
        response.end(JSON.stringify({ error: { message: "Service unavailable", type: "server_error" } }));
    });
    const ollamaServer = await startServer(t, (request, response) => {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ model: "ollama-local-model", message: { role: "assistant", content: "ollama-should-not-be-called" } }));
    });
    const model = vllmModel(server, ollamaServer);
    const chains = createChains(model);
    await assert.rejects(chains.general.invoke({ query: "Hello" }, { signal: AbortSignal.timeout(10000) }), (error) => {
        assert.match(error.message, /Service unavailable/);
        return true;
    });
    t.diagnostic(`vLLM request count: ${requests.length}`);
    assert.equal(requests.length, 2, `Expected exactly 2 requests (1 initial + 1 retry with maxRetries=1), got ${requests.length}`);
    assert.equal(requests[0].path, "/v1/chat/completions");
    assert.equal(requests[1].path, "/v1/chat/completions");
    assert.equal(ollamaServer.requests.length, 0, "Ollama fixture should receive zero requests");
    const countAtReject = requests.length;
    const ollamaCountAtReject = ollamaServer.requests.length;
    await new Promise((resolve) => setTimeout(resolve, 500));
    assert.equal(requests.length, countAtReject, "vLLM retries should stop after rejection");
    assert.equal(ollamaServer.requests.length, ollamaCountAtReject, "Ollama request count should remain zero");
});

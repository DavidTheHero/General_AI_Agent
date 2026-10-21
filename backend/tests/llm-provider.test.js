import test from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { once } from "node:events";
import { ChatOllama } from "@langchain/ollama";
import { createModel, createChains, getModelName } from "../llm.js";

async function modelServer(t, { content = '{"answer":"Local answer"}', status = 200, compatible = false, outputMode = 'json_schema' } = {}) {
    const requests = [];
    const server = createServer(async (request, response) => {
        let body = "";
        for await (const chunk of request) body += chunk;
        requests.push({ path: request.url, authorization: request.headers.authorization, body: JSON.parse(body) });
        response.writeHead(status, { "content-type": "application/json" });
        response.end(JSON.stringify(status === 200 ? {
            id: "local-test", object: "chat.completion", created: 0, model: "local-model",
            choices: [{ index: 0, message: { role: "assistant", content }, finish_reason: "stop" }],
            usage: { prompt_tokens: 10, completion_tokens: 5, total_tokens: 15 },
        } : { error: { message: "Authentication required", type: "authentication_error" } }));
    });
    server.listen(0, "127.0.0.1");
    await once(server, "listening");
    t.after(() => new Promise((resolve, reject) => {
        server.close((error) => error ? reject(error) : resolve());
        server.closeAllConnections();
    }));
    const model = createModel({ env: {
        LLM_PROVIDER: "vllm", VLLM_MODEL: "local-model",
        VLLM_BASE_URL: `http://127.0.0.1:${server.address().port}/v1`,
        VLLM_API_KEY: "test-local-key",
        LLM_STRUCTURED_OUTPUT: outputMode,
        ...(compatible ? { LLM_PROVIDER: 'openai-compatible', LLM_MODEL: 'mac-model',
            LLM_BASE_URL: `http://127.0.0.1:${server.address().port}/v1/`, LLM_API_KEY: 'mac-key' } : {}),
    } });
    return { model, requests };
}

test("Ollama remains the default and honors its existing settings", () => {
    const defaults = createModel({ env: {} });
    assert.ok(defaults instanceof ChatOllama);
    assert.equal(defaults.model, "llama3.1:8b-instruct-q4_K_M");
    assert.equal(defaults.baseUrl, "http://localhost:11434");
    const custom = createModel({ env: { LLM_PROVIDER: "ollama", OLLAMA_HOST: "http://127.0.0.1:11435", OLLAMA_MODEL: "custom" } });
    assert.equal(custom.model, "custom");
    assert.equal(custom.baseUrl, "http://127.0.0.1:11435");
});

test('OpenAI-compatible servers use their configured model, URL and key without vendor-specific extras', async (t) => {
    const { model, requests } = await modelServer(t, { compatible: true });
    assert.deepEqual(await createChains(model).general.invoke({ query: 'Hello Mac' }), { answer: 'Local answer' });
    assert.equal(requests[0].path, '/v1/chat/completions');
    assert.equal(requests[0].authorization, 'Bearer mac-key');
    assert.equal(requests[0].body.model, 'mac-model');
    assert.equal(requests[0].body.chat_template_kwargs, undefined);
    assert.equal(getModelName({ LLM_PROVIDER: 'openai-compatible', LLM_BASE_URL: 'http://mac:1234/v1', LLM_MODEL: 'mac-model' }), 'mac-model');
    assert.equal(getModelName({ LLM_PROVIDER: 'vllm', VLLM_MODEL: 'docker-model' }), 'docker-model');
    assert.throws(() => createModel({ env: { LLM_PROVIDER: 'openai-compatible' } }), /LLM_BASE_URL and LLM_MODEL/);
});

test('JSON-object compatibility mode supplies the schema in the prompt and still validates locally', async (t) => {
    const { model, requests } = await modelServer(t, { compatible: true, outputMode: 'json_object' });
    assert.deepEqual(await createChains(model).general.invoke({ query: 'Hello Mac' }), { answer: 'Local answer' });
    assert.deepEqual(requests[0].body.response_format, { type: 'json_object' });
    assert.match(requests[0].body.messages[0].content, /"required":\["answer"\]/);
    const invalid = await modelServer(t, { compatible: true, outputMode: 'json_object', content: '{"answer":false}' });
    await assert.rejects(createChains(invalid.model).general.invoke({ query: 'Hello' }));
});

test("vLLM chains send chat completions with JSON schema and thinking disabled", async (t) => {
    const { model, requests } = await modelServer(t);
    assert.deepEqual(await createChains(model).general.invoke({ query: "Hello" }), { answer: "Local answer" });
    assert.equal(requests.length, 1);
    const { path, authorization, body } = requests[0];
    assert.equal(path, "/v1/chat/completions");
    assert.equal(authorization, "Bearer test-local-key");
    assert.equal(body.model, "local-model");
    assert.equal(body.temperature, 0);
    assert.equal(body.max_tokens, 4096);
    assert.deepEqual(body.chat_template_kwargs, { enable_thinking: false });
    assert.equal(body.response_format.type, "json_schema");
    assert.equal(body.response_format.json_schema.schema.properties.answer.type, "string");
    assert.equal(body.tools, undefined);
    assert.match(body.messages.at(-1).content, /Hello/);
});

test("vLLM output still undergoes local schema validation", async (t) => {
    const { model } = await modelServer(t, { content: '{"answer":false}' });
    await assert.rejects(createChains(model).general.invoke({ query: "Hello" }));
});

test("vLLM loop schemas omit redundant record key types and retain argument values", async (t) => {
    const { model, requests } = await modelServer(t, { content: '{"action":"tool","tool":"calculator","arguments":{"calculator_expression":"23*7"}}' });
    const result = await createChains(model).loop.invoke({
        query: "Calculate 23 times 7", context: "{}", reference_date: "2026-10-17", timezone: "Europe/London",
        allowed_tools: ["calculator"], available_tools: "calculator", observations: "[]", remaining_steps: 1,
    });
    assert.deepEqual(result.arguments, { calculator_expression: "23*7" });
    assert.equal(result.message, "");
    const schema = requests[0].body.response_format.json_schema.schema;
    assert.equal(schema.properties.arguments.propertyNames, undefined);
    assert.deepEqual(schema.properties.tool.enum, ["", "calculator"]);
    assert.deepEqual(schema.required, ["action", "tool", "arguments", "message"]);
});

test("vLLM authentication failures surface without switching providers", async (t) => {
    const { model, requests } = await modelServer(t, { status: 401 });
    await assert.rejects(createChains(model).general.invoke({ query: "Hello" }), /Authentication required/);
    assert.equal(requests.length, 1);
});

test("unknown providers fail explicitly", () => {
    assert.throws(() => createModel({ env: { LLM_PROVIDER: "typo" } }), /Unsupported LLM_PROVIDER/);
});

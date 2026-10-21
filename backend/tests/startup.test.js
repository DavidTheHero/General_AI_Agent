import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { selectServices, runServices } from '../../scripts/up.mjs';

const reachable = async () => ({ ok: true, json: async () => ({ models: [] }) });
const unreachable = async () => { throw new Error('connection refused'); };

test('Docker startup checks the selected server model and never starts Ollama', async () => {
    const env = { LLM_PROVIDER: 'openai-compatible', LLM_BASE_URL: 'http://mac:18035/v1', LLM_MODEL: 'mac-model', LLM_API_KEY: 'test-key' };
    let requested;
    const services = await selectServices(env, async (url, options) => {
        requested = { url: String(url), authorization: options.headers.Authorization };
        return { ok: true, json: async () => ({ data: [{ id: 'mac-model' }] }) };
    });
    assert.deepEqual(services.map(s => s.name), ['api', 'ui', 'trading']);
    assert.deepEqual(requested, { url: 'http://mac:18035/v1/models', authorization: 'Bearer test-key' });
    await assert.rejects(selectServices(env, async () => ({ ok: true, json: async () => ({ data: [{ id: 'other-model' }] }) })), /mac-model.*other-model/);
    await assert.rejects(selectServices(env, unreachable), /configured model server/);
    await assert.rejects(selectServices(env, async () => ({ ok: false, status: 401 })), /401/);
});

test('one-command startup reuses a running Ollama server', async () => {
    const services = await selectServices({}, reachable);
    assert.deepEqual(services.map(s => s.name), ['api', 'ui', 'trading']);
    assert.ok(services.find(s => s.name === 'trading').args.includes('--parent-pipe'));
});

test('one-command startup owns Ollama only when the local server is unavailable', async () => {
    const services = await selectServices({ OLLAMA_HOST: 'http://127.0.0.1:11434' }, unreachable);
    assert.equal(services[0].name, 'ollama');
    assert.equal(services[0].command, 'ollama');
    assert.deepEqual(services[0].args, ['serve']);
    await assert.rejects(selectServices({ OLLAMA_HOST: 'http://model-server:11434' }, unreachable), /remote Ollama/);
});

test('one-command startup refuses a reachable service that is not Ollama', async () => {
    await assert.rejects(selectServices({}, async () => ({ ok: false })), /Ollama/);
    await assert.rejects(selectServices({}, async () => ({ ok: true, json: async () => ({}) })), /Ollama/);
});

test('service failure stops siblings and closes the runtime parent pipe', { timeout: 10000 }, async () => {
    const signals = new EventEmitter();
    const services = [
        { name: 'runtime', command: process.execPath, args: ['-e', 'process.stdin.resume(); process.stdin.on("end", () => process.exit(0))'], parentPipe: true },
        { name: 'failure', command: process.execPath, args: ['-e', 'setTimeout(() => process.exit(7), 100)'] },
    ];
    assert.equal(await runServices(services, { signals, log: () => {} }), 7);
    assert.equal(signals.listenerCount('SIGTERM'), 0);
});

test('Ctrl+C stops owned services through the runtime parent pipe', { timeout: 10000 }, async () => {
    const signals = new EventEmitter();
    const timer = setTimeout(() => signals.emit('SIGINT'), 250);
    try {
        const code = await runServices([
            { name: 'runtime', command: process.execPath, args: ['-e', 'process.stdin.resume(); process.stdin.on("end", () => process.exit(0))'], parentPipe: true },
        ], { signals, log: () => {} });
        assert.equal(code, 0);
    } finally { clearTimeout(timer); }
});

test('missing executable stops the group and reports failure', { timeout: 10000 }, async () => {
    assert.equal(await runServices([
        { name: 'missing', command: 'general-ai-missing-executable-test', args: [] },
        { name: 'sibling', command: process.execPath, args: ['-e', 'setInterval(() => {}, 1000)'] },
    ], { signals: new EventEmitter(), log: () => {} }), 1);
});

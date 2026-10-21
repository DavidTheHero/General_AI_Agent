import test from 'node:test';
import assert from 'node:assert/strict';
import { createToolContext, loopInstructions } from '../context.js';
import { createAgent } from '../agent.js';

test('tool definitions stay deferred until relevant retrieval or explicit search', async () => {
    const defined = [];
    const entries = [
        { name: 'market_brief', description: 'Yahoo market news headlines today' },
        { name: 'weather', description: 'Weather forecast city temperature' },
        ...Array.from({ length: 50 }, (_, i) => ({ name: `simulation_${i}`, description: 'Synthetic simulation portfolio backtest' })),
    ];
    const context = createToolContext(entries, async (entry) => {
        defined.push(entry.name);
        return { ...entry, input_schema: { type: 'object' } };
    });
    context.search('Yahoo market news today');
    let packet = await context.packet(entries.map(e => e.name));
    assert.deepEqual(defined, ['market_brief']);
    assert.deepEqual(packet.tools.map(t => t.name), ['tool_search', 'market_brief']);
    context.search('weather temperature');
    packet = await context.packet(['weather']);
    assert.deepEqual(packet.tools.map(t => t.name), ['tool_search', 'weather']);
    assert.equal(defined.includes('simulation_0'), false);
    assert.deepEqual(context.search('simulation_17', ['weather']), []);
});

test('schema loading is bounded and unavailable definitions remain explicit', async () => {
    const entries = Array.from({ length: 8 }, (_, i) => ({ name: `lookup_${i}`, description: 'lookup records' }));
    const context = createToolContext(entries, async (entry) => {
        if (entry.name === 'lookup_0') throw new Error('MCP unavailable');
        return { ...entry, input_schema: { description: 'x'.repeat(5000) } };
    });
    context.search('lookup');
    const packet = await context.packet(entries.map(e => e.name));
    assert.ok(JSON.stringify(packet.tools).length < 8500);
    assert.match(JSON.stringify(packet.unavailable), /MCP unavailable/);
    assert.deepEqual((await context.packet([])).tools, []);
});

test('ordinary prompts omit unrelated trading protocols', () => {
    const ordinary = loopInstructions(['finance_workspace']);
    assert.doesNotMatch(ordinary, /sector|reserved.final|nine fixed|L252/);
    assert.match(loopInstructions(['trading_sector_research_start']), /reserved|holdout/);
    assert.match(loopInstructions(['resolve_company']), /verify|identity/);
});

test('news context omits trading schemas and returns a complete requested report immediately', async () => {
    let calls = 0;
    const report = { workflow: 'morning', data: { news: [] }, warnings: [] };
    const agent = createAgent({ trading: {}, tools: { execute: async () => ({ answer: 'Ready', report }),
        financeCatalog: async () => [] }, chains: { loop: { invoke: async (input) => {
            calls++;
            assert.ok(input.allowed_tools.includes('tool_search'));
            assert.ok(input.allowed_tools.includes('finance_workspace'));
            assert.doesNotMatch(input.available_tools, /trading_experiment_start|trading_dataset_create/);
            assert.ok(input.available_tools.length < 8500);
            return { action: 'tool', tool: 'finance_workspace', arguments: { workflow: 'morning', date: '2026-10-21', timezone: 'Europe/London' } };
        } } } });
    const result = await agent.run('yahoo market news today');
    assert.equal(calls, 1);
    assert.equal(result.responses[0].report, report);
});

test('model tool search can recover a tool missed by the original query', async () => {
    let calls = 0;
    const agent = createAgent({ tools: { execute: async (decision) => {
        assert.equal(decision.tool_choice, 'weather'); return 'London forecast';
    }, financeCatalog: async () => [] }, chains: { loop: { invoke: async (input) => {
        if (calls++ === 0) return { action: 'tool', tool: 'tool_search', arguments: { query: 'weather city forecast' } };
        if (calls === 2) {
            assert.ok(input.allowed_tools.includes('weather'));
            return { action: 'tool', tool: 'weather', arguments: { location: 'London' } };
        }
        return { action: 'finish', message: 'London forecast' };
    } } } });
    const result = await agent.run('Help me plan my day');
    assert.equal(result.usage.weather, 1);
    assert.equal(result.usage.tool_search, 1);
    assert.match(result.answer, /London forecast/);
});

test('a report does not prematurely finish an explicit additional task', async () => {
    let calls = 0;
    const executed = [];
    const choices = [
        { action: 'tool', tool: 'finance_workspace', arguments: { workflow: 'morning', date: '2026-10-21', timezone: 'Europe/London' } },
        { action: 'tool', tool: 'weather', arguments: { location: 'London' } },
        { action: 'finish', message: 'Market report and London weather retrieved.' },
    ];
    const agent = createAgent({ tools: { financeCatalog: async () => [], execute: async decision => {
        executed.push(decision.tool_choice);
        return decision.tool_choice === 'weather' ? 'London weather' : { report: { workflow: 'morning', data: {}, warnings: [] } };
    } }, chains: { loop: { invoke: async () => { calls++; return choices.shift(); } } } });
    const result = await agent.run('Yahoo market news today and weather in London');
    assert.deepEqual(executed, ['finance_workspace', 'weather']);
    assert.equal(calls, 3);
    assert.equal(result.metadata.agent_trace[0].stop_reason, 'complete');
});

test('a report does not substitute for requested interpretation', async () => {
    let calls = 0;
    const agent = createAgent({ tools: { financeCatalog: async () => [], execute: async () => ({ report: { workflow: 'morning', data: {}, warnings: [] } }) },
        chains: { loop: { invoke: async () => ++calls === 1 ?
            { action: 'tool', tool: 'finance_workspace', arguments: { workflow: 'morning', date: '2026-10-21', timezone: 'Europe/London' } } :
            { action: 'finish', message: 'Evidence-based interpretation.' } } } });
    const result = await agent.run('Explain the market report');
    assert.equal(calls, 2);
    assert.match(result.answer, /interpretation/);
});

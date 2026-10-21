# Deferred tool discovery and scoped model context

## Scope

Implement the discover-and-load pattern from [Anthropic's advanced tool-use design](https://www.anthropic.com/research/advanced-tool-use) in the existing Qwen/OpenAI-compatible runtime. This is a host-side implementation: no Claude API, provider-specific `defer_loading` field, generated-code execution or framework migration is required.

Baseline measured on the Mac Qwen 9B server: the `yahoo market news today` request sent 39,453 characters / 9,491 input tokens to select a tool, followed by another 10,790-token decision after a complete report. One diagnostic run took 112 seconds; approximately 95 seconds were prompt processing and the Yahoo tool took 2 seconds.

## Context contract

- Keep searchable names, descriptions and aliases in the backend registry. Full schemas are constructed only when selected. Metadata is not a permission grant.
- Prefetch at most three local keyword matches for the current request. Include `tool_search` so the model can discover other capabilities by purpose or exact name without receiving the entire catalog.
- A search prioritizes up to three matches. Retain at most six loaded tools per request, and cap serialized model-facing tool definitions at 8,000 characters. This is a character bound, not a tokenizer-exact token budget. Omitted/unavailable definitions are identified explicitly; a specific subsequent search can reprioritize them.
- Search only within the current workflow's permitted tools. Existing execution allow-lists, argument validation, company identity requirements and trading protocol validation remain authoritative. Model transport schemas enumerate the exposed tool names.
- Load live MCP argument schemas only for selected MCP tools. Discovery itself never executes those tools. Report missing catalogs/schemas as unavailable context and allow the model to choose another capability.
- Search and loaded definitions belong to one request segment. Concurrent requests and later topic changes do not share that mutable selection.
- Load a compact core policy, then finance or trading instructions only when the selected capabilities need them. Selected trading tools retain their own protocol descriptions and schemas. Company investigation retains its existing state-controlled resolver/verification/report sequence.
- Place stable tool definitions before changing query, memory and observations. Provider caching is an optimization whose hit rate must be measured, not assumed.
- Preserve bounded existing observation previews and retain complete reports outside model context for the UI. External results are evidence, never instructions.

## Completion and limits

A complete report for an explicit single news/brief/report/overview/dashboard request returns immediately. Conservatively continue for interpretation requests and when the wording contains conjunctions or separators suggesting another task; existing explicit company/market-report workflows retain their established completion rules. Discovery consumes the existing loop step budget, so search cannot create an unbounded inference loop.

Initial lexical retrieval may miss a capability; the model can call `tool_search` with other terms. Rare synonyms and multilingual requests depend on that recovery path. A schema that cannot fit the tool-definition bound needs a narrower tool interface. Native provider tool calling and server-side schema compatibility remain separate concerns.

## Validation

Offline regressions cover deferred schema construction, relevant-only news context, discovery recovery, unavailable schemas, scope filtering, size bounds, domain instructions and report completion with additional tasks. Existing company identity and actual-process trading tests must continue passing.

Compare actual prompt/completion tokens, server prompt-processing/generation time, model-call count and task outcome against the baseline on the same provider. Report live samples separately from deterministic offline tests; do not treat one warm-cache measurement as a latency guarantee.

## Windows-to-Mac live sample, 21 October 2026

Same Docker Model Runner `docker.io/local/qwen35-9b:16k`, JSON-object mode and full application tool availability:

| Measurement | Baseline | Deferred context |
|---|---:|---:|
| News first-call input tokens | 9,491 | 1,991 |
| News first-call prompt characters | 39,453 | 7,308 |
| News model calls | 2 | 1 |
| News end-to-end sample | 111.8 s | 25.7 s |

The improved news request returned a Yahoo morning report with one `finance_workspace` execution. Server prompt processing was 12.2 s and generation 6.3 s; the rest included request overhead and the approximately 2 s tool execution. The sample had zero cached input tokens. Calculator regression: 23 times 7 returned 161 with one calculator execution and two small model calls, 14.7 s total (838 and 872 input tokens).

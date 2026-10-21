import { test } from "node:test";
import assert from "node:assert/strict";
import { createAgent } from "../agent.js";

test("agent run response includes connected model name", async () => {
  const agent = createAgent({
    chains: {
      router: { invoke: async () => ({ tool_choice: "none", direct_answer: "ok" }) },
      general: { invoke: async () => ({ answer: "ok" }) },
    },
    tools: {},
    store: { recent: () => [], query: async () => [], addEntry: () => {} },
  });
  const result = await agent.run("hello");
  assert.equal(typeof result.model, "string");
  assert.ok(result.model.length > 0);
});

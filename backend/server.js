import { createApp } from "./app.js";
import { createAgent } from "./agent.js";
import { SemanticMemoryStore } from "./memory.js";
import { FinanceMcpClient } from "./finance/client.js";
import { createTools } from "./tools.js";
import { createWorkspace } from "./finance/workspace.js";
import { TradingMcpClient } from "./trading/client.js";

const store = new SemanticMemoryStore();
const finance = new FinanceMcpClient();
const trading = new TradingMcpClient();
const app = createApp({ agent: createAgent({ store, tools: createTools(fetch, finance), trading }), store, workspace: createWorkspace(finance), trading });
const port = Number(process.env.PORT || 2610);
const server = app.listen(port, "127.0.0.1", () => {
    console.log(`Assistant API: http://localhost:${port}`);
});
server.on("error", async (error) => {
    console.error(error.message);
    store.close();
    await finance.close();
    await trading.close();
    process.exitCode = 1;
});
for (const signal of ["SIGINT", "SIGTERM"]) {
    process.on(signal, () => server.close(async () => { store.close(); await finance.close(); await trading.close(); process.exit(0); }));
}

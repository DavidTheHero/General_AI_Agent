import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { pythonCommand } from "../finance/client.js";

const mode = process.argv[2];
if (!["runtime", "mcp_server"].includes(mode)) throw new Error("Use runtime or mcp_server");
const child = spawn(pythonCommand(), ["-m", `trading_agent.${mode}`, ...process.argv.slice(3)], {
    cwd: fileURLToPath(new URL("../../", import.meta.url)), stdio: "inherit",
});
child.on("error", (error) => { console.error(error.message); process.exitCode = 1; });
child.on("exit", (code) => { process.exitCode = code ?? 1; });
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => child.kill(signal));

import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { pythonCommand } from "../finance/client.js";

const mode = process.argv[2];
if (!["runtime", "mcp_server"].includes(mode)) throw new Error("Use runtime or mcp_server");
const isRuntime = mode === "runtime";
const args = ["-m", `trading_agent.${mode}`, ...process.argv.slice(3)];
if (isRuntime) args.push("--parent-pipe");
const child = spawn(pythonCommand(), args, {
    cwd: fileURLToPath(new URL("../../", import.meta.url)),
    stdio: isRuntime ? ["pipe", "inherit", "inherit"] : "inherit",
    shell: false,
    windowsHide: true,
    detached: isRuntime && process.platform === 'win32',
});
child.on("error", (error) => { console.error(error.message); process.exitCode = 1; });
child.on("exit", (code) => { process.exitCode = code ?? 1; });
if (isRuntime) {
    child.stdin.on("error", (error) => {
        if (error.code === "EPIPE") return;
        console.error(error.message);
        process.exitCode = 1;
    });
    for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => child.stdin.end());
} else {
    for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => child.kill(signal));
}

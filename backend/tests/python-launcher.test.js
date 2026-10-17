import test from "node:test";
import assert from "node:assert/strict";
import { spawn, execFile } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { setTimeout as delay } from "node:timers/promises";
import { pythonCommand } from "../finance/client.js";

const root = fileURLToPath(new URL("../../", import.meta.url));
const execute = promisify(execFile);

for (const platform of ["win32", "darwin", "linux"]) {
    test(`Python discovery preserves executable paths and platform defaults: ${platform}`, () => {
        const directory = join(root, "venv with spaces");
        const expected = join(directory, ".venv", platform === "win32" ? "Scripts/python.exe" : "bin/python");
        assert.equal(pythonCommand({ platform, rootDirectory: directory, env: {}, exists: () => true }), expected);
        assert.equal(pythonCommand({ platform, env: {}, exists: () => false }), platform === "win32" ? "python" : "python3");
        assert.equal(pythonCommand({ platform, env: { MCP_PYTHON: "explicit path with spaces/python" },
            exists: () => { throw Error("Override must take precedence"); } }), "explicit path with spaces/python");
    });
}

test("foreground launcher loss stops its runtime and durable worker without replay", { timeout: 45000 }, async () => {
    const directory = await mkdtemp(join(tmpdir(), "launcher spaces "));
    const child = spawn(process.execPath, ["backend/trading/cli.js", "runtime", "--port", "0"], {
        cwd: root, env: { ...process.env, TRADING_DATA_DIR: directory, MCP_PYTHON: pythonCommand() },
        stdio: ["ignore", "pipe", "pipe"], windowsHide: true,
    });
    let logs = "";
    child.stdout.on("data", value => { logs += value; });
    child.stderr.on("data", value => { logs += value; });
    const reopen = `import json,sys,time
from trading_agent.runtime import JobManager
deadline=time.monotonic()+15
while True:
 try:
  manager=JobManager(sys.argv[1]); break
 except ValueError:
  if time.monotonic()>deadline: raise
  time.sleep(.1)
try:
 assert not manager.processes
 print(json.dumps([manager.get(j['id']) for j in manager.list()['jobs']]))
finally: manager.close()
`;
    async function inspectClosed() {
        const { stdout } = await execute(pythonCommand(), ["-c", reopen, directory], {
            cwd: root, timeout: 20000, windowsHide: true,
        });
        return JSON.parse(stdout);
    }
    try {
        const deadline = Date.now() + 15000;
        while (!/127\.0\.0\.1:(\d+)/.test(logs)) {
            assert.equal(child.exitCode, null, logs);
            assert.equal(child.signalCode, null, logs);
            assert.ok(Date.now() < deadline, logs);
            await delay(50);
        }
        const port = logs.match(/127\.0\.0\.1:(\d+)/)[1];
        const token = (await readFile(join(directory, "token"), "utf8")).trim();
        const response = await fetch(`http://127.0.0.1:${port}/jobs`, {
            method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
            body: JSON.stringify({ mode: "demo", start: "2026-10-14", config: { symbols: ["DEMO_A"], interval: "30m" } }),
            signal: AbortSignal.timeout(5000),
        });
        assert.equal(response.status, 200, logs);
        const job = await response.json();
        assert.equal(job.status, "running");
        child.kill("SIGTERM");
        const saved = await inspectClosed();
        assert.equal(saved.length, 1);
        assert.ok(["complete", "stopped"].includes(saved[0].status), JSON.stringify(saved));
        if (saved[0].status === "complete") assert.equal(saved[0].report?.status, "complete");
        else assert.ok(saved[0].report || /no work is resumed/.test(saved[0].error), JSON.stringify(saved));
    } finally {
        if (child.exitCode === null && child.signalCode === null) child.kill("SIGTERM");
        await inspectClosed();
        child.stdout.destroy(); child.stderr.destroy();
        await rm(directory, { recursive: true, force: true });
    }
});

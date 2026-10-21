import { spawn } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { pythonCommand } from '../backend/finance/client.js';
import { modelSettings } from '../backend/model-provider.js';

const root = fileURLToPath(new URL('../', import.meta.url));

export async function selectServices(env = process.env, fetchImpl = fetch) {
    const settings = modelSettings(env);
    const services = [
        { name: 'api', command: process.execPath, args: ['backend/server.js'] },
        { name: 'ui', command: process.execPath, args: ['node_modules/vite/bin/vite.js', '--config', 'frontend/vite.config.js'] },
        { name: 'trading', command: pythonCommand({ env }), args: ['-m', 'trading_agent.runtime', '--parent-pipe'], parentPipe: true },
    ];
    if (settings.provider !== 'ollama') {
        let response;
        try {
            response = await fetchImpl(`${settings.baseURL}/models`, {
                headers: { Authorization: `Bearer ${settings.apiKey}` }, signal: AbortSignal.timeout(5000),
            });
        } catch {
            throw new Error('Cannot reach the configured model server. Check LLM_BASE_URL (or VLLM_BASE_URL), Docker and network access.');
        }
        if (!response.ok) throw new Error(`Model discovery returned HTTP ${response.status}. Check the base URL (including /v1) and API key.`);
        const models = (await response.json()).data;
        if (!Array.isArray(models)) throw new Error('Model server did not return an OpenAI-compatible model list.');
        if (!models.some(model => model.id === settings.model)) {
            throw new Error(`Configured model ${settings.model} is unavailable. Available models: ${models.map(model => model.id).join(', ') || '(none)'}`);
        }
        return services;
    }
    const host = new URL(settings.baseURL);
    let response;
    try {
        response = await fetchImpl(new URL('/api/tags', host), { signal: AbortSignal.timeout(2000) });
    } catch {
        if (!['localhost', '127.0.0.1', '[::1]'].includes(host.hostname)) {
            throw new Error('Cannot reach remote Ollama. Start that server or correct OLLAMA_HOST in .env.');
        }
        return [{ name: 'ollama', command: 'ollama', args: ['serve'] }, ...services];
    }
    if (!response.ok || !Array.isArray((await response.json()).models)) {
        throw new Error('OLLAMA_HOST did not return an Ollama model list. Check the service and URL in .env.');
    }
    return services;
}

export function runServices(services, { signals = process, log = console.error } = {}) {
    return new Promise((resolve) => {
        const children = new Set();
        let stopping = false;
        let exitCode = 0;
        let timer;
        const finish = () => {
            if (children.size) return;
            clearTimeout(timer);
            signals.off('SIGINT', interrupt);
            signals.off('SIGTERM', interrupt);
            resolve(exitCode);
        };
        const stop = (code) => {
            if (stopping) return;
            stopping = true;
            exitCode = code;
            log('Stopping application services…');
            for (const child of children) {
                // The trading runtime drains jobs and releases its lease when this pipe closes.
                if (child.parentPipe) child.stdin.end();
                else child.kill('SIGTERM');
            }
            timer = setTimeout(() => {
                log('Shutdown timed out; terminating remaining application processes.');
                exitCode = 1;
                for (const child of children) child.kill('SIGKILL');
            }, 30000);
            finish();
        };
        const interrupt = () => stop(0);
        signals.on('SIGINT', interrupt);
        signals.on('SIGTERM', interrupt);
        for (const service of services) {
            log(`Starting ${service.name}…`);
            const child = spawn(service.command, service.args, {
                cwd: root, shell: false, windowsHide: true,
                stdio: service.parentPipe ? ['pipe', 'inherit', 'inherit'] : 'inherit',
                detached: Boolean(service.parentPipe && process.platform === 'win32'),
            });
            child.parentPipe = service.parentPipe;
            children.add(child);
            child.stdin?.on('error', (error) => {
                if (error.code !== 'EPIPE') { log(`${service.name}: ${error.message}`); stop(1); }
            });
            child.on('error', (error) => { log(`${service.name}: ${error.message}`); stop(1); });
            child.on('close', (code) => {
                children.delete(child);
                if (!stopping) { log(`${service.name} exited (${code}).`); stop(code ?? 1); }
                finish();
            });
        }
        finish();
    });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
    try {
        const services = await selectServices();
        console.log('Open http://localhost:2611 after startup. Ctrl+C stops services started here.');
        process.exitCode = await runServices(services);
    } catch (error) {
        console.error(error.message);
        process.exitCode = 1;
    }
}

import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

export default defineConfig(({ mode }) => {
    const env = loadEnv(mode, process.cwd(), "");
    const target = env.AGENT_API_URL || "http://localhost:2610";
    return {
        root: fileURLToPath(new URL(".", import.meta.url)),
        plugins: [react()],
        server: {
            host: "127.0.0.1", port: 2611, strictPort: true,
            proxy: Object.fromEntries(["/query", "/health", "/memory", "/finance", "/trading"].map((path) => [path, { target, timeout: 300000, proxyTimeout: 300000 }])),
        },
        test: { environment: "jsdom", include: ["src/**/*.test.jsx"] },
    };
});

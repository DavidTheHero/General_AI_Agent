export function modelSettings(env = process.env) {
    const provider = (env.LLM_PROVIDER || 'ollama').trim().toLowerCase();
    if (provider === 'ollama') return {
        provider, model: env.OLLAMA_MODEL || 'llama3.1:8b-instruct-q4_K_M',
        baseURL: env.OLLAMA_HOST || 'http://localhost:11434',
    };
    if (!['vllm', 'openai-compatible'].includes(provider)) {
        throw new Error(`Unsupported LLM_PROVIDER: ${provider}. Use ollama, vllm or openai-compatible.`);
    }
    const model = provider === 'vllm' ? env.VLLM_MODEL || 'qwen3.8-27b' : env.LLM_MODEL;
    const baseURL = provider === 'vllm' ? env.VLLM_BASE_URL || 'http://127.0.0.1:18020/v1' : env.LLM_BASE_URL;
    if (!model || !baseURL) throw new Error('Set LLM_BASE_URL and LLM_MODEL for the OpenAI-compatible server.');
    const url = new URL(baseURL);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) {
        throw new Error('Model base URL must use HTTP(S), without credentials, query or fragment. Use LLM_API_KEY for authentication.');
    }
    const structuredOutput = env.LLM_STRUCTURED_OUTPUT || 'json_schema';
    if (!['json_schema', 'json_object'].includes(structuredOutput)) {
        throw new Error('LLM_STRUCTURED_OUTPUT must be json_schema or json_object.');
    }
    return {
        provider, model, baseURL: baseURL.replace(/\/+$/, ''),
        apiKey: (provider === 'vllm' ? env.VLLM_API_KEY : env.LLM_API_KEY) || 'local-no-key',
        disableThinking: provider === 'vllm' || env.LLM_DISABLE_THINKING === 'true',
        structuredOutput,
    };
}

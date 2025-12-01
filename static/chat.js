(function () {
    const config = window.AGENT_CONFIG || {};
    const form = document.getElementById("chat-form");
    const textarea = document.getElementById("query-input");
    const chatBox = document.getElementById("chat-box");
    const sendBtn = document.getElementById("send-btn");
    const chatEndpoint = config.chatEndpoint;

    if (!form || !textarea || !chatEndpoint) {
        return;
    }

    function escapeHtml(text) {
        const div = document.createElement("div");
        div.textContent = text || "";
        return div.innerHTML;
    }

    function formatText(text) {
        return escapeHtml(text).replace(/\n/g, "<br>");
    }

    function appendMessage(author, html, role = "assistant", pending = false) {
        const wrapper = document.createElement("div");
        wrapper.className = `message ${role}${pending ? " pending" : ""}`;
        wrapper.innerHTML = `<strong>${author}</strong><p>${html}</p>`;
        chatBox.appendChild(wrapper);
        chatBox.scrollTop = chatBox.scrollHeight;
        return wrapper;
    }

    function renderAssistant(wrapper, raw, elapsedMs) {
        wrapper.classList.remove("pending");
        wrapper.classList.add("assistant");
        if (!raw) {
            wrapper.innerHTML = "<strong>Assistant</strong><p>(no response)</p>";
            return;
        }
        if (raw.error) {
            wrapper.innerHTML = `<strong>Assistant</strong><p class="error">${escapeHtml(raw.error)}</p>`;
            return;
        }
        const segments = Array.isArray(raw.responses) && raw.responses.length
            ? raw.responses.map((resp) => `<p>${escapeHtml(resp.answer || "")}</p>`).join("")
            : `<p>${formatText(raw.answer || raw.reply || "")}</p>`;
        let timingsHtml = "";
        const timings = raw.timings || (raw.metadata && raw.metadata.timings);
        if (timings) {
            const items = Object.entries(timings)
                .map(([name, stats]) => `<li>${escapeHtml(name)} – avg ${stats.avg_ms}ms (${stats.count}×)</li>`)
                .join("");
            timingsHtml = `<details><summary>Timings</summary><ul>${items}</ul></details>`;
        }
        const latency = typeof elapsedMs === "number"
            ? `<span class="latency-chip">${elapsedMs.toFixed(0)} ms</span>`
            : "";
        wrapper.innerHTML = `<strong>Assistant</strong>${segments}<div class="meta-row">Tools: ${escapeHtml(JSON.stringify(raw.usage || {}))} | Tokens: ${escapeHtml(JSON.stringify(raw.token_usage || {}))} ${latency} ${timingsHtml}</div>`;
    }

    form.addEventListener("submit", async function (event) {
        event.preventDefault();
        const query = (textarea.value || "").trim();
        if (!query) {
            return;
        }
        appendMessage("You", formatText(query), "user");
        const assistantMsg = appendMessage("Assistant", "Thinking...", "assistant", true);
        sendBtn.disabled = true;
        textarea.value = "";
        textarea.focus();
        const start = performance.now();

        try {
            const response = await fetch(chatEndpoint, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ query }),
            });
            const data = await response.json();
            if (!response.ok || data.error) {
                throw new Error(data.error || "Request failed.");
            }
            const elapsed = performance.now() - start;
            renderAssistant(assistantMsg, data.item ? data.item.raw : data, elapsed);
        } catch (error) {
            assistantMsg.classList.remove("pending");
            assistantMsg.innerHTML = `<strong>Assistant</strong><p class="error">${escapeHtml(error.message)}</p>`;
        } finally {
            sendBtn.disabled = false;
        }
    });
})();

import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App.jsx";

const reply = (answer = "50") => ({
    answer, responses: [{ query: "Add numbers", answer }], usage: { calculator: 1 },
    token_usage: { calls: 1 }, latency_ms: 123,
    metadata: { stock_context: { recent_symbols: ["AAPL"] }, timings: {} },
    timings: { lm_router: { avg_ms: 12, count: 1 } },
});

beforeEach(() => {
    sessionStorage.clear();
    vi.stubGlobal("fetch", vi.fn(async (url) => ({ ok: true, json: async () => url === "/health" ? { status: "ok" } : reply() })));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("React chat", () => {
    it("renders the empty conversation and health state", async () => {
        render(<App />);
        expect(screen.getByText(/Start with a question/)).toBeTruthy();
        expect(await screen.findByText("Connected")).toBeTruthy();
        expect(screen.getByRole("button", { name: "Send" }).disabled).toBe(true);
    });

    it("drafts a starter question without sending it", async () => {
        const user = userEvent.setup();
        render(<App />);
        await user.click(screen.getByRole("button", { name: "Give me a company research brief on Nvidia" }));
        expect(screen.getByLabelText("Message").value).toBe("Give me a company research brief on Nvidia");
        expect(document.activeElement).toBe(screen.getByLabelText("Message"));
        expect(fetch.mock.calls.filter(([url]) => url === "/query")).toHaveLength(0);
    });

    it("sends messages, shows results and retains context for follow-ups", async () => {
        const user = userEvent.setup();
        render(<App />);
        await user.type(screen.getByLabelText("Message"), "Add numbers");
        await user.click(screen.getByRole("button", { name: "Send" }));
        expect(await screen.findByText("50")).toBeTruthy();
        expect(screen.getByText("123 ms")).toBeTruthy();
        const first = JSON.parse(fetch.mock.calls.find(([url]) => url === "/query")[1].body);
        expect(first.metadata.session_id).toBeTruthy();
        await user.type(screen.getByLabelText("Message"), "Again{Enter}");
        await waitFor(() => expect(fetch.mock.calls.filter(([url]) => url === "/query")).toHaveLength(2));
        const second = JSON.parse(fetch.mock.calls.filter(([url]) => url === "/query")[1][1].body);
        expect(second.metadata.session_id).toBe(first.metadata.session_id);
        expect(second.metadata.stock_context.recent_symbols).toEqual(["AAPL"]);
    });

    it("resets backend memory and starts a new session", async () => {
        const user = userEvent.setup();
        render(<App />);
        await user.type(screen.getByLabelText("Message"), "Hello{Enter}");
        await screen.findByText("50");
        const old = JSON.parse(sessionStorage.getItem("assistant-conversation")).session_id;
        await user.click(screen.getByRole("button", { name: "Reset conversation" }));
        await screen.findByText(/Start with a question/);
        const reset = JSON.parse(fetch.mock.calls.find(([url]) => url === "/memory/reset")[1].body);
        expect(reset.session_id).toBe(old);
        expect(JSON.parse(sessionStorage.getItem("assistant-conversation")).session_id).not.toBe(old);
    });

    it("shows errors and re-enables sending after failure", async () => {
        fetch.mockImplementation(async (url) => ({ ok: url === "/health", json: async () => ({ detail: "Ollama unavailable" }) }));
        const user = userEvent.setup();
        render(<App />);
        await user.type(screen.getByLabelText("Message"), "Hello{Enter}");
        expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Ollama unavailable");
        await user.type(screen.getByLabelText("Message"), "Retry");
        expect(screen.getByRole("button", { name: "Send" }).disabled).toBe(false);
    });

    it("preserves the conversation when reset fails", async () => {
        const user = userEvent.setup();
        render(<App />);
        await user.type(screen.getByLabelText("Message"), "Hello{Enter}");
        await screen.findByText("50");
        fetch.mockResolvedValue({ ok: false, json: async () => ({ detail: "Reset failed" }) });
        await user.click(screen.getByRole("button", { name: "Reset conversation" }));
        expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Reset failed");
        expect(screen.getByText("50")).toBeTruthy();
    });

    it("keeps Shift+Enter as a newline and escapes model output", async () => {
        fetch.mockImplementation(async (url) => ({ ok: true, json: async () => url === "/health" ? {} : reply("<script>alert(1)</script>") }));
        const user = userEvent.setup();
        const { container } = render(<App />);
        await user.type(screen.getByLabelText("Message"), "Line one{Shift>}{Enter}{/Shift}Line two");
        expect(screen.getByLabelText("Message").value).toBe("Line one\nLine two");
        expect(fetch.mock.calls.some(([url]) => url === "/query")).toBe(false);
        await user.click(screen.getByRole("button", { name: "Send" }));
        await screen.findByText("<script>alert(1)</script>");
        expect(container.querySelector("script")).toBeNull();
    });

    it("restores conversation after a reload", async () => {
        sessionStorage.setItem("assistant-conversation", JSON.stringify({ session_id: "saved", metadata: {}, messages: [{ role: "user", text: "Previous question" }] }));
        render(<App />);
        expect(screen.getByText("Previous question")).toBeTruthy();
    });
});

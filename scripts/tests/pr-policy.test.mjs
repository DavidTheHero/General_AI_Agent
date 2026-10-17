import test from "node:test";
import assert from "node:assert/strict";
import { validatePullRequest } from "../pr-policy.mjs";

const valid = {
    branch: "fix/42-worker-shutdown",
    body: "Closes #42\n\n## Change\nBounded shutdown.\n\n## Validation\nChecks pending while draft.\n\n## Review\nLead review pending.",
    files: [{ filename: "trading_agent/runtime.py", status: "modified" }],
};

test("a scoped draft may declare pending checks and review", () => {
    assert.deepEqual(validatePullRequest(valid), { issueNumber: 42, errors: [] });
});

test("main, missing issue IDs and malformed branch names are rejected", () => {
    for (const branch of ["main", "fix/worker-shutdown", "fix/0-empty", "fix/42-", "fix/42-../main"]) {
        assert.match(validatePullRequest({ ...valid, branch }).errors.join("\n"), /task branch/);
    }
});

test("the closing issue must match the branch and appear outside examples", () => {
    for (const reference of ["Closes #4", "Related to #42", "<!-- Closes #42 -->", "```\nCloses #42\n```", "`Closes #42`"]) {
        const body = valid.body.replace("Closes #42", reference);
        assert.match(validatePullRequest({ ...valid, body }).errors.join("\n"), /Closes #42/);
    }
    assert.deepEqual(validatePullRequest({ ...valid, body: valid.body.replace("Closes #42", "Fixes #42") }).errors, []);
});

test("empty or commented-out evidence sections do not pass", () => {
    for (const heading of ["Change", "Validation", "Review"]) {
        const body = valid.body.replace(new RegExp(`## ${heading}\\n[^\\n]+`), `## ${heading}\n<!-- pending -->`);
        assert.match(validatePullRequest({ ...valid, body }).errors.join("\n"), new RegExp(heading));
    }
});

test("environment secrets and generated artifacts are rejected, including nested paths", () => {
    for (const filename of [".env", "backend/.env.production", "frontend/.ENV.local", ".venv/pyvenv.cfg", "node_modules/pkg/index.js", "frontend/dist/index.html", "artifacts/trading/run/report.json", "_edit.py", "semantic_memory.db", "jobs.sqlite-wal"]) {
        assert.match(validatePullRequest({ ...valid, files: [{ filename, status: "added" }] }).errors.join("\n"), /local\/generated/);
    }
});

test("environment examples and deletions of accidental local files remain allowed", () => {
    const files = [{ filename: ".env.example", status: "modified" }, { filename: ".env", status: "removed" }];
    assert.deepEqual(validatePullRequest({ ...valid, files }).errors, []);
});

test("renaming a local secret does not hide its source path", () => {
    const files = [{ filename: "configuration.txt", previous_filename: ".env", status: "renamed" }];
    assert.match(validatePullRequest({ ...valid, files }).errors.join("\n"), /\.env/);
});

test("empty file lists cannot produce a successful scope check", () => {
    assert.match(validatePullRequest({ ...valid, files: [] }).errors.join("\n"), /no changed files/);
});

test("an incomplete GitHub file list cannot pass scope review", () => {
    assert.match(validatePullRequest({ ...valid, changedFileCount: 2 }).errors.join("\n"), /complete PR scope/);
    assert.deepEqual(validatePullRequest({ ...valid, changedFileCount: 1 }).errors, []);
});

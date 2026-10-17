const branchPattern = /^(?:feat|fix|test|docs|chore|review)\/([1-9]\d*)-[a-z0-9]+(?:-[a-z0-9]+)*$/;

export function validatePullRequest({ branch, body = "", files = [], changedFileCount = files.length }) {
    const errors = [];
    const match = branchPattern.exec(branch || "");
    const issueNumber = match ? Number(match[1]) : null;
    if (!match) errors.push("Use a task branch such as fix/123-worker-shutdown.");
    // Template comments and code examples are not closing references or evidence.
    const text = body.replace(/<!--[\s\S]*?-->/g, "").replace(/```[\s\S]*?```/g, "").replace(/`[^`\n]*`/g, "");
    const references = [...text.matchAll(/\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#([1-9]\d*)\b/gi)].map((item) => Number(item[1]));
    if (issueNumber && !references.includes(issueNumber)) errors.push(`Include Closes #${issueNumber} in the PR body, matching the task branch.`);
    for (const heading of ["Change", "Validation", "Review"]) {
        const section = new RegExp(`^## ${heading}\\s*\\n([\\s\\S]*?)(?=^## |$(?![\\s\\S]))`, "mi").exec(text);
        if (!section?.[1].trim()) errors.push(`Provide a non-empty '${heading}' section in the PR body.`);
    }
    if (!files.length) errors.push("The PR has no changed files to review.");
    if (files.length !== changedFileCount) errors.push(`Cannot review the complete PR scope: GitHub reports ${changedFileCount} files but returned ${files.length}. Split the PR or investigate pagination.`);
    for (const file of files) {
        // Removing an accidentally tracked local file must remain possible.
        if (file.status === "removed") continue;
        for (const filename of [file.filename, file.previous_filename].filter(Boolean)) {
            const path = filename.replaceAll("\\", "/").toLowerCase();
            const parts = path.split("/");
            const localEnv = parts.some((part) => part === ".env" || (part.startsWith(".env.") && part !== ".env.example"));
            const generated = parts.some((part) => ["node_modules", ".venv"].includes(part))
                || path.startsWith("frontend/dist/") || path.startsWith("artifacts/trading/")
                || path === "_edit.py" || /\.(?:db|sqlite|sqlite3)(?:-(?:wal|shm|journal))?$/.test(path);
            if (localEnv || generated) errors.push(`Exclude local/generated file from the PR: ${filename}`);
        }
    }
    return { issueNumber, errors };
}

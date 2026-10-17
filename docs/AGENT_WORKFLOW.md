# Agent-assisted delivery through GitHub

GitHub issues define the work; commits and pull requests define the delivered change. `Communication.md` can keep a local handoff/index, but a message saying "complete" does not mean code has been merged. Keep local prompt transcripts and generated logs under ignored `artifacts/trading/`; publish concise, sanitized evidence on the issue or PR.

## Ownership and states

The lead investigates, defines a bounded ticket, reviews proposals and independently verifies the result. The implementer owns the ticket's allowed files. A local API model has no Git or shell access merely because it received a prompt: the lead must apply its reviewed proposal and execute commands, or provide an explicitly scoped tool harness.

| State | Evidence needed to advance |
| --- | --- |
| Ready | Issue has a problem, evidence, allowed files, dependencies, acceptance criteria and required checks. |
| In progress | Implementer claims the issue, records the base SHA and owns an isolated task branch/worktree. |
| Locally verified | Scoped changes and local results are available. The issue remains open. |
| In review | Draft PR links the issue, implementation provenance, test results and unresolved findings. |
| Merge ready | Independent lead review covers the final head SHA; applicable checks pass and findings are resolved. |
| Delivered | PR is merged into its intended base, merge SHA is recorded and post-merge verification is complete. |
| Blocked | The issue records the actual dependency/error and what can proceed independently. |

Implementation tickets close through `Closes #<issue>` when their PR merges into the default branch. Review-only tickets close when their accepted evidence is published and linked to the delivery PR; unresolved fixes get linked tickets rather than disappearing from the report. A new push invalidates the lead's earlier head-SHA review.

## 1. Open a bounded ticket and establish the baseline

Use the **Agent task** issue form. Include file/line references, observed versus expected behavior, allowed files, excluded work, implementer, lead reviewer, dependencies and observable acceptance criteria. Do not assign overlapping file ownership to concurrent workers. Split implementation, independent review and unrelated features into separate issues.

Record `git status --short`, `git rev-parse HEAD`, relevant Node/Python/provider versions and applicable baseline commands. Identify user-owned changes and existing failures. Never reset, stash, commit or overwrite somebody else's work to create a clean starting point. Keep secrets and the real `.env` out of prompts, issues and commits.

For the current pending work, see [Windows delivery #2](https://github.com/DavidTheHero/General_AI_Agent/issues/2), [Docker provider/LLM-01 delivery #3](https://github.com/DavidTheHero/General_AI_Agent/issues/3), [WIN-02 review #6](https://github.com/DavidTheHero/General_AI_Agent/issues/6) and [CI-03 review #7](https://github.com/DavidTheHero/General_AI_Agent/issues/7). Earlier local test results are not results for a published PR revision.

## 2. Create one branch and worktree per ticket

Use `<type>/<issue>-<short-name>` with type `feat`, `fix`, `test`, `docs`, `chore` or `review`:

```powershell
git fetch origin
git worktree add -b fix/42-worker-shutdown ../General_AI_Agent-42 origin/main
```

Run implementation commands inside the new worktree. Leave the original dirty checkout in place. An uncommitted prerequisite is not available in a new branch: deliver it first, or declare a stacked branch/PR dependency and rebase/retest when its base changes. Copy only the files/hunks owned by the issue, comparing their saved hashes before applying a returned proposal. Never copy the entire dirty tree to make tests pass.

Each worktree needs compatible dependencies/interpreters. On Windows use `.venv/Scripts/python.exe`; on POSIX use `.venv/bin/python`. Verify the actual Node used by npm as well as child processes. A bundled Node executable on PATH does not necessarily replace the adjacent Node used by a system `npm.cmd`; an explicit supported `node <npm-cli.js> ...` is valid. Keep machine-specific paths out of committed configuration.

## 3. Hand off a bounded implementation

Post an issue update with the assignee, branch, base SHA and current status. For Docker Qwen, verify `/v1/models` and the running container immediately before the handoff. Record the exact returned model ID and provider; do not substitute Ollama or an alias silently. The current local service has used `http://127.0.0.1:18020/v1` with model ID `qwen3.8-27b`; verify it rather than assuming it is unchanged.

Give the model the issue and acceptance criteria, relevant source and schemas, baseline failures, allowed paths, regression requirements and required response format. State whether it can execute tools. For API-only handoffs, request a proposed file or bounded patch and prohibit execution claims. Save the prompt, response and source hashes in ignored artifacts. Keep credentials and unrelated repository content out of the request.

The lead reads every proposed diff before applying it. Apply only the allowed files if their hashes still match the handoff. Run the relevant tests independently. Send concrete findings and actual failures back to the implementer; review each correction before assigning more work. Do not accept a model's self-report, startup alone or mocked tests as evidence of live integration.

## 4. Make scoped, reviewable commits

Review both unstaged and staged changes. Stage named files, never the whole shared workspace:

```powershell
git add -- backend/tests/example.test.js
git diff --cached --name-only
git diff --cached --check
git diff --cached
git commit -m "Cover worker shutdown regression (#42)"
git push -u origin fix/42-worker-shutdown
```

Use the configured contributor identity. Record model/provider and review provenance in the issue/PR; do not invent a model's GitHub identity or a human approval. Exclude `.env`, `_edit.py`, virtual environments, dependencies, generated databases, build output and trading artifacts. A new test file must be included in the staged review even though ordinary `git diff` omits untracked files.

## 5. Open a draft PR and return concrete review findings

Use the PR template with `Closes #42`, and non-empty **Change**, **Validation** and **Review** sections. Drafts may say checks/review are pending. Put multiline descriptions and comments in files so the CLI preserves their exact text:

```powershell
gh pr create --draft --base main --head fix/42-worker-shutdown --title "Cover worker shutdown regression" --body-file ../ticket-42-pr.md
gh pr checks <pr-number>
```

Report commands, versions, exit codes, baseline failures, known limits and actual platform results for this branch. Link any relevant CI runs and sanitized reproduction evidence. For code changes run `npm test` and `npm run build`; Python/trading changes also require the unittest suite, offline demo and applicable actual-process lifecycle/snapshot checks. Live-model integration requires an actual model/app request in addition to mocked tests. Public CI cannot access a developer's loopback Docker service; keep ordinary unit tests offline.

Documentation/workflow-only changes may document reproduced pre-existing application failures with evidence that application source is unchanged. Never waive a failure introduced by the PR. Windows portability/provider delivery requires its applicable application checks to pass. A platform is unverified until its tests actually run. Re-run affected checks after corrections or base changes.

The **Ticket and scope** policy check tests its own validator, verifies the branch/closing-issue relationship and required PR sections, confirms the linked number identifies a real issue, and rejects accidental local/generated files. It does not establish correctness, prove a reviewer is independent, or replace application/platform CI. Changes to the gate itself require careful lead review.

The lead records findings against the PR's exact head SHA. Blocking findings get a correction and another review; a new push requires another final-SHA check. Record an independent AI lead's review as such. When one GitHub account both commits and posts the review, do not represent its comment as a separate GitHub user's approving review.

## 6. Merge only the reviewed revision, then verify delivery

Before marking a PR ready, check its final diff, base/dependencies, unresolved conversations, applicable tests and latest head SHA. Record the lead's review and remaining limitations on the PR. Use GitHub's formal approving review when a distinct eligible reviewer is available; never forge or bypass one.

```powershell
gh pr view <pr-number> --json headRefOid,baseRefName,isDraft,reviewDecision,statusCheckRollup
gh pr checks <pr-number> --watch --fail-fast
gh pr ready <pr-number>
gh pr merge <pr-number> --squash --match-head-commit <reviewed-head-sha>
gh pr view <pr-number> --json state,mergedAt,mergeCommit
```

Do not use `--admin`, auto-merge or a force push to evade a gate. The lead merges only within the user's authorized scope, using `--match-head-commit` to prevent a newer unreviewed commit being merged. If a distinct human approval is required, wait for that actual review.

Verify the merged revision in a clean/detached worktree, re-run the applicable smoke/checks, and record the merge SHA/result on the issue or PR. Confirm the intended issue closed. If verification fails, reopen or link a concrete follow-up and assess a focused revert; do not silently call it delivered. Delete only the task's remote branch and clean owned worktree after verifying the merge and an empty worktree status. Keep dirty worktrees for review. Never pull/reset the original dirty checkout as part of cleanup.

## Repository merge gates

The bootstrap configures a PR requirement, the successful **Ticket and scope** Actions check, up-to-date branches, conversation resolution and protection against force pushes/deletion on `main`, including administrators. With the current single-account workflow, formal approving-review count is zero; independent lead review is a documented process requirement. Add a real required approval when an eligible second account/reviewer is available. Do not label this arrangement as enforced independent human approval.

Application/platform CI is delivered separately with the Windows foundation. Once its Windows/macOS jobs have succeeded and their exact check names are known, add them as required checks for application delivery; retain explicit reports of unverified environments until then. Repository settings are external state: record configuration changes and verify them through GitHub, rather than assuming this document enforces them.

See GitHub's [issue form syntax](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/syntax-for-issue-forms) and [protected branch behavior](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches).

# Peer review: Windows runtime shutdown (WIN-02, issue #6)

Review date: 17 October 2026. The original WIN-02 checkpoint below was **report only**, subsequently committed locally as `0d38fcf`. Its target was `a5488e73ab6a6a161339c49d2c0a157d9e470664` plus the dirty Windows/provider overlay, rather than immutable `main` alone. It reused evidence after an interrupted Qwen session. The later lead verification and CI-03 sections explicitly update that historical checkpoint; application changes remain local, not merged delivery.

## Provenance

- The overlay is **36 dirty files** (23 modified + 13 untracked). SHA-256 manifest: `artifacts/trading/windows-review/peer-review/overlay-hashes.json`. An earlier ACK cited 38; that count was incorrect — the lead's comparison found no missing files and no hash mismatches before this report. The 36 hashes themselves are not repeated here; the lead verified all hashes and the critical source matches before this writing.
- `Communication.md` is a mutable coordination log; it is cited for provenance, not reviewed.
- Environment: Windows 11, Node 24.20.0, repository venv Python 3.12.15. Model provider `my-vllm` (`qwen3.8-27b`, Docker vLLM at `127.0.0.1:18020/v1`), verified by the lead before this handoff.

## Evidence collected for this ticket

All paths below are relative to `artifacts/trading/windows-review/`.

### Targeted native-process/I/O and fault-injected tests (24, Windows)

Exact command per module: `.venv/Scripts/python.exe -m unittest discover -s trading_agent/tests -p <module> -v`.

| Module (run individually) | Result | Log |
| --- | --- | --- |
| `test_runtime_lock.py` | 7 pass, OK (0.184 s) | `peer-review/logs/test_runtime_lock.log` |
| `test_platform_runtime.py` | 8 pass, OK (8.153 s) | `peer-review/logs/test_platform_runtime.log` |
| `test_atomic_reporting.py` | 9 pass, OK (3.418 s) | `peer-review/logs/test_atomic_reporting.log` |

Qwen executed the three modules; the lead independently re-ran the same 24 tests (`lead-peer-verification/test_*.py.log`). The `NativeCommandError` lines inside the logs are PowerShell stderr transport, not test failures.

### Concurrent-close probe (designed by the lead; executed separately by lead and Qwen)

- Design: `lead-peer-verification/concurrent_close.py` (lead). Qwen copied it to `peer-review/concurrent-close/concurrent_close.py` and ran it with `PYTHONPATH` set to the repository root using the venv Python. These are two executions of one lead-designed probe, not two independently designed probes.
- What it exercises: a real child waiting on stdin (`python -c "import sys; sys.stdin.buffer.read()"`) — a process the `JobManager` owns, not a trading-policy workload — plus a real SQLite database, file lease and process monitor; every wait is bounded (5 s) with force-kill cleanup in `finally`.
- Scheduling: the first `close()` thread pauses after snapshotting active job IDs and before `stop()`; a second `close()` completes (stops the child, joins the monitors, closes the database and lease); the first `close()` then resumes `stop()`.
- Observed in both executions: `ProgrammingError: Cannot operate on a closed database.`; `manager_closed: true`; child exit code `[0]`. Qwen result: `peer-review/concurrent-close/concurrent-close-result.json` (job `de94f12a…`); lead result: `lead-peer-verification/concurrent-close-result.json` (job `6c26f8d4…`).
- Interpretation: the probe's final assertion asserts that **the bug exists**; exit code 0 is a reproduction, not fix acceptance.

## Finding P2 — `JobManager.close` is not safe under concurrent calls (`trading_agent/runtime.py:341`)

- **Mechanism.** Call A (the first close) snapshots the active job IDs under the manager lock, releases the lock, and pauses before `stop()`. Call B then completes shutdown: it stops the child, joins the monitors, closes the SQLite database and releases the lease. When A resumes, its `stop()`/job `get()` accesses the now-closed database.
- **Proven:** a concurrent library-call race on the real SQLite/lease/monitor stack, on Windows.
- **Not proven:** a concurrent call path in the production foreground launcher; any portfolio data corruption; any failure of ordinary sequential shutdown. The existing 24 targeted tests do not cover simultaneous `close()`.
- **Severity:** P2 — a lifecycle race with data-integrity adjacency and a narrow trigger window; no user-visible corruption demonstrated in this scope.

## Expected correction (proposal only — nothing implemented by this ticket)

- Serialize the complete shutdown behind a **dedicated close guard**. Never hold the existing manager lock while joining monitors.
- On a failed shutdown with live workers remaining, retain the database and lease (do not release them out from under live workers); release the guard on every exception path so a retry can succeed.
- **Regression spec:** two close threads plus a controlling thread that releases paused A. B must not return while A is paused; both calls must return error-free, the child must actually exit, no monitors may remain, the lease must be reacquired and the database reopened without replaying interrupted work.
- The original bug-probe schedule cannot be reused by inverting its assertion: under the serialized fix, paused A would deadlock. A new regression probe is required.

## Invariants and limitations

- Required behavioral constraints are completed-bar-only policy inputs, next-open target execution, explicit currency/timezone units, auditable costs, durable jobs, atomic progress snapshots, explicit interrupted portfolios, and no silent replay. This review makes no policy/accounting changes. The targeted tests alone do not establish that all invariants hold.
- This ticket is report only: no fix, no push, no PR, no branch change; the only file staged and committed is this document. All user dirty files remain untouched.
- Not run by this ticket: the offline policy demo, the full Python suites, macOS execution and hosted CI. The lead's separate full-suite, fresh-install and Docker-provider results are not re-asserted here.
- **Status: READY_FOR_REVIEW.** CI-03 (issue #7, branch `fix/7`) stays queued until the lead accepts this report; it must explicitly inherit this document.

## Lead follow-up: WIN-02-F1 correction and independent verification

17 October 2026: the lead accepted the reproduced P2 finding and reviewed successive OpenCode Qwen proposals. Incorrect `Thread.join()` assertions, missing concurrent callers, unsafe cleanup and an incorrect expected failure status were returned for correction. Accepted source is in `trading_agent/runtime.py:94` and `:342`, with the new `trading_agent/tests/test_runtime_shutdown.py`.

The correction adds five runtime lines: a dedicated close lock and a public wrapper around the unchanged former shutdown body. The existing manager lock is not held across monitor joins. Source-byte comparison confirmed that removing only those insertions reconstructs the preserved dirty baseline exactly. Original user work was not replaced or committed.

Two new tests use actual owned stdin-reading child processes, SQLite and file leases. Concurrent close callers are controlled by a separate release event; neither may finish prematurely, both must return without errors, workers and monitors must exit, and reopening must reacquire ownership without replay. Injected stop failure must retain a usable database and lease, and a bounded retry must finish. These two tests are additional to the historical 24, giving 26 targeted tests.

The lead ran the race test against the uncorrected source: it failed because the second close returned while the first was paused. It passed with the correction. Deliberately removing the guard reproduced that failure; restoring the exact source passed again. This is regression/mutation evidence, rather than relying on Qwen's execution claims. The demonstrated trigger remains concurrent library calls; a production launcher trigger or portfolio corruption has not been demonstrated.

Final Windows 11 checks used Node 24.20.0 and Python 3.12.15, with both model URLs unavailable and `PYTHONUTF8=0`:

| Command from repository root | Independently observed result |
| --- | --- |
| `npm test` | 105 backend + 33 frontend pass |
| `npm run build` | Pass |
| `.venv/Scripts/python.exe -m unittest discover -s trading_agent/tests -v` | 179 pass, 124.577 s |
| Same unittest command with `-p test_runtime_shutdown.py` | 2 pass |
| Same command with `-p test_runtime_lock.py`, `test_platform_runtime.py`, `test_atomic_reporting.py`, separately | 7 + 8 + 9 pass |
| `.venv/Scripts/python.exe -m trading_agent demo --start 2026-10-14 --output artifacts/trading/windows-review/close-fix/offline-demo` | Complete, 29 fills; metrics equal to baseline and fills/equity CSV bytes identical |

Evidence under `artifacts/trading/windows-review/close-fix/`: `accepted.patch` (against the dirty Windows baseline), `lead-red.log`, `lead-guard-mutation.log`, `lead-mutation-result.json`, `final-results.json`, `final-*.log`, and `final-demo-comparison.json`. Earlier 177-test results predate the correction. The new source and tests are locally reviewed/verified and remain uncommitted alongside the preserved Windows foundation. This report commit does not deliver that application code. The tests, source review and deterministic ledger comparison provide scoped evidence; none is a blanket proof of all trading invariants.

## CI-03: setup, platform CI and deployment audit

OpenCode `my-vllm/qwen3.8-27b`, served by Docker vLLM, source-reviewed this report at `0d38fcf` plus the recorded overlay and the separate workflow at `0806e34`. The lead checked its returned claims against source and evidence, rejecting invented test counts and setup defects before accepting the corrected scope. Qwen ran no test, install or deployment commands for CI-03. No secrets were supplied. Source hashes and reviewed responses are under `artifacts/trading/windows-review/ci03-lead/`.

Declared floors are consistent: Node 22.13+ in `package.json:7` and Python 3.11+ in `pyproject.toml:10`, `README.md:7` and `CONTRIBUTING.md:5`. Installed pandas/numpy/matplotlib metadata requires Python 3.11 or later; MCP 2.3 requires 3.10 or later. The executed Windows environment is Node 24.20/Python 3.12.15. **Validation gap:** the declared minimum versions have not run. Acceptance before claiming those floors verified is successful installation and applicable checks at those versions; no incompatibility was demonstrated.

The proposed `.github/workflows/platform.yml:10` runs Node 24/Python 3.12 on Windows and macOS: fresh npm/Python installs, tests, build and dated offline demo. **Validation gap:** neither hosted platform job has run for this local overlay. Acceptance is successful jobs against the eventual delivery PR revision. macOS runtime, signal behavior and launchd execution remain unverified. The separate workflow PR #8 has actual passing Linux checks (90 backend, 33 frontend, 153 Python, build and demo); those counts belong to its different source revision, not this Windows overlay.

`backend/finance/client.js:10` honors `MCP_PYTHON`, then the platform-specific repository venv, then `python`/`python3`. Hosted Linux CI actually passed with `MCP_PYTHON=python`; Windows/macOS automatic fallback was not separately demonstrated. Fresh Windows installation in a space-containing venv passed finance requirements, editable `.[mcp]` and `pip check`; a separate base-only install was not run. README quickstart already installs `.[mcp]`; optional MCP versus base/demo installation is intentional. Evidence: `fresh-install-results.json` and `clean-overlay-results.json`.

The independently executed Windows checks and unchanged demo ledger are recorded above. Offline checks used unavailable model endpoints. `backend/llm.js:84` retains Ollama as default, with explicit vLLM opt-in and rejection of unknown providers. Docker/OpenCode model verification does not by itself validate the application's model integration; the earlier live-app request is separate evidence, not a CI-03 run.

`deploy/install_service.py:42` rejects installation outside macOS; Windows rejection was executed and exited 2 before filesystem/service mutation. This does not verify launchd. The trading service captures exported `TRADING_DATA_DIR`/`TRADING_RUNTIME_PORT`; the web service loads `.env` through Node's `--env-file-if-exists` (`deploy/install_service.py:19`, `deploy/README.md:77`). Linux `flock` ownership is valid independently of an installer; the deployment guide already advises using an existing Linux supervisor. Windows foreground operation was exercised; Windows service installation is unsupported by the shipped installer. Network/cloud-synced filesystems remain unverified. No dependency addition, Linux installer or unrelated refactor is justified by this audit.

CI-03 is **accepted source-review evidence**, with the minimum-version and hosted-platform validation gaps above still open under delivery #2. Neither this report nor successful Linux workflow checks mean Windows/macOS delivery has merged. Implementation/review issues remain distinct from delivery status.

## Delivery verification (issue #2)

The sections above are historical checkpoints for the original dirty Windows/provider overlay. The delivery branch `fix/2-windows-runtime` starts at workflow merge `e7932d2` and copies only the reviewed Windows files. It excludes the vLLM client, dependency, provider tests and provider configuration, which belong to issue #3. The user's original checkout is preserved. The accepted review reports are included here so issues #6/#7 have durable published evidence linked to the Windows delivery.

Independent checks on this separated Windows branch, 17 October 2026: fresh `npm ci`, `npm test` (94 backend + 33 frontend), `npm run build`, full Python unittest (179 tests, 72.155 s), and the dated offline demo all pass. Removing the close guard fails the original race regression; restoring the exact runtime SHA-256 `89d0c7e1dd925cce80248893643bb70d734c7ff0f3c67b45edc6dc3247b206be` passes both shutdown tests. These counts differ from the earlier combined overlay because the provider regressions are intentionally excluded. Commands and logs are under ignored `artifacts/trading/delivery/windows-branch/` and `windows-mutation.log`.

The platform workflow now proposes three full-check jobs: Windows and macOS on Node 24/Python 3.12, plus Linux at declared minimum Node 22.13.0/Python 3.11. Dependencies/actions are pinned consistently with the existing application workflow; model URLs are unavailable so ordinary checks cannot use a developer's local model service. Adding these jobs is not a passing result. Actual hosted results, exact reviewed head, merge SHA and post-merge checks are recorded on the PR linked from [delivery issue #2](https://github.com/DavidTheHero/General_AI_Agent/issues/2). macOS launchd installation, physical console keypresses, network/cloud filesystems and Windows service installation are not established by these tests; the installer does not provide Windows services.

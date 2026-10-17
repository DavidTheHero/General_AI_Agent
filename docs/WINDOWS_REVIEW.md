# Windows support review

Review date: 17 October 2026. Starting revision: `a5488e73ab6a6a161339c49d2c0a157d9e470664`.

## Baseline and ownership

The starting working tree contained modified `trading_agent/runtime.py` and untracked `trading_agent/filelock.py` and `_edit.py`. These are user work, not clean-HEAD changes. A binary patch, copies and original hashes are retained under ignored `artifacts/trading/windows-review/baseline/`. `_edit.py` must remain untouched. The lease implementation is reviewed as existing work to extend, not replaced with the HEAD version.

Host: Windows 11 Pro x64, build 26200. PATH initially resolves Node 19.1.0 / npm 8.19.3 and Python 3.10.9, below project requirements. Verification uses bundled Node 24.21.0 by prepending its directory to PATH and repository `.venv/Scripts/python.exe` (Python 3.12.15). The existing venv has no pip module; installation itself is not verified. Installed packages include mcp 2.3.0, yfinance 1.7.0, pandas 3.0.6, numpy 2.3.5, pydantic 2.14.1, exchange-calendars 4.13.2 and matplotlib 3.11.2.

Git is 2.39.2.windows.1; the shell is Windows PowerShell 5.1.26100.9711. Python's text encoding is CP1252 with UTF-8 mode disabled; the filesystem encoding is UTF-8.

Implementation is delegated through the loopback Ollama HTTP API, not the default Codex configuration (which selects a different model/provider). Before dispatch, `/api/version`, `/api/tags` and `/api/ps` verify Ollama 0.40.5 and local `qwen3.8:27b`, digest `aaee06c39dcf2437cde036998d960e1fc1494b8191be7cc9657d01e509097813`, Q4_K_M, 27.3B parameters. Each task records the provider evidence, exact prompt and response under the ignored review directory. The lead reviews candidate files before application and independently runs checks.

That describes the initial delegation phase. Several candidates required correction for unrelated syntax changes, invented interfaces, ineffective process tests or cleanup gaps. The Ollama CUDA runner also repeatedly failed with illegal-memory-access errors. A temporary, hidden Ollama process on port 11435 used the same verified model digest and installed CUDA 12 backend; speculative decoding was disabled per request. When the user instructed the lead to stop Qwen delegation, the active request was cancelled and the lead completed implementation, corrections, regression tests, CI and documentation directly. No further coding tasks were delegated. The temporary Ollama process and model runner were removed; the original service on port 11434 and the user's Codex configuration were left intact. Ollama GPU stability itself has not been repaired or qualified.

### Baseline results (before applying delegated changes)

| Command | Result |
| --- | --- |
| `npm test`, default Node 19 | Fails resolving the literal backend test glob; frontend not reached |
| `npm run build`, default Node 19 | Fails importing `node:util.styleText` |
| `npm test`, Node 24 | Backend 89/90 pass; memory fixture cleanup fails EPERM because cleanup runs before SQLite close; frontend not reached |
| `npm run test:frontend`, Node 24 | 33/33 pass |
| `npm run build`, Node 24 | Pass |
| `.venv/Scripts/python.exe -m unittest discover -s trading_agent/tests -v` | 153 tests; five errors and one failure. SQLite file handles prevent cleanup in research restart, two sector and two weekly tests. Weekly report test reads UTF-8 output using the Windows locale and fails its en-dash assertion. |
| `.venv/Scripts/python.exe -m trading_agent demo --start 2026-10-14 --output artifacts/trading/windows-review/baseline/demo` | Pass, synthetic full-session report, 29 fills, no errors |

## Prioritized source audit and acceptance criteria

References below identify the original source symbols; line numbers can move with edits.

| Priority | Evidence / affected files | Expected behavior and acceptance criteria |
| --- | --- | --- |
| P0 | HEAD `trading_agent/runtime.py` imports `fcntl` unconditionally. Existing uncommitted `filelock.py:FileLease` adds msvcrt but buffers byte initialization, maps every lock error to contention and only closes on LeaseBusy. `JobManager.__init__` releases the lease without closing an initialized database after reconciliation failure. | Exclusive nonblocking ownership on Windows and POSIX. Actual independent-process contention, same-process contention, paths with spaces, owner close/death and injected initialization failure must pass. Never unlink the lease file or leak handles. Preserve POSIX flock. |
| P0 | `runtime.py:JobManager.stop` sends SIGTERM; `cli.py`, `research.py`, `daily_research.py`, `sector_research.py`, `weekly_research.py` read parent stdin then call `os.kill(self, SIGTERM)`. Windows SIGTERM uses termination rather than the Python cleanup handler. | Portable cooperative cancellation and parent-death detection across every worker entrypoint. A real worker must preserve interrupted positions, last completed bars and partial reports; blocked workers need a bounded force-stop fallback with explicit missing-result notice. No silent replay on recovery. |
| P1 | `runtime.py:main` creates manager before HTTP bind without a cleanup guard; shutdown relies on Unix-like signals. `backend/trading/cli.js` forwards child.kill signals that forcibly terminate Python on Windows. | Bind failure releases SQLite and lease. A Windows foreground launcher supports a tested graceful shutdown route, waits for workers and exits. Runtime crash, restart and explicit interrupted state are exercised with real processes. Existing macOS foreground/launchd lifecycle remains supported. |
| P1 | An actual Node-launcher termination probe initially reopened the durable demo as `interrupted`, despite the parent-pipe change. Windows libuv child ownership terminated Python with its Node parent before graceful cleanup. | Windows runtime child uses a separate process group while retaining its Node child reference and stdin lifetime pipe. The identical probe must reopen as `stopped` or truly `complete`, with reports or an explicit missing-result notice. Keep MCP and macOS lifecycle separate. The [Node child-process documentation](https://nodejs.org/api/child_process.html#optionsdetached) describes this Windows detached-child behavior. |
| P1 | `backend/finance/client.js:pythonCommand` correctly recognizes `.venv/Scripts/python.exe`, but falls back to `python3` even on Windows (often an App Execution Alias). Finance and trading share this function. | Explicit MCP_PYTHON wins; platform-appropriate venv and fallback are deterministic, tested with spaces and argument arrays, no shell interpolation. A supported Python is required and documented. |
| P1 | Baseline Python tests use sqlite connection context managers without closing handles; Windows disallows deleting the open databases. `backend/tests/tools.test.js` registers directory removal before closing the second database. | Close database resources before deleting fixtures; keep assertions. Whole suites pass without suppressing cleanup errors or relying on garbage collection. |
| P1 | `atomic_text` writes UTF-8 but many readers use locale defaults. Weekly report baseline fails on CP1252. `reporting.py:atomic_text` already uses same-directory replacement. | Explicit UTF-8 at affected artifact boundaries and regressions with non-ASCII content under a Windows locale. Readers must never see partial progress JSON; don't weaken atomic replacement or checksum validation. |
| P1 | Independent Windows concurrency probe: 2,000 `atomic_text` writes with two JSON readers produced 2,326 reader/writer exceptions, including replacement `PermissionError(13, 'Access is denied')`. Python readers can temporarily hold the destination against Windows replacement. | Bounded retry of transient Windows replacement denial without unlinking the old destination. Surface persistent errors and retain old snapshot; concurrent readers must never observe partially written JSON. Test actual contention and a held destination handle. |
| P1 | `deploy/install_service.py` deliberately emits macOS launchd specifications and `.venv/bin/python`; `deploy/README.md` says the runtime requires POSIX locking. Setup examples only show Unix commands. No checked-in CI workflows. | Retain macOS launchd. Provide precise Windows PowerShell setup/foreground deployment and graceful-stop/recovery guidance, document service limitations and ACL differences. Add Windows/macOS CI with supported Node/Python, full suites/build and offline runtime checks. Do not claim unexecuted macOS/service installation results. |
| P2 | Dataset/source snapshots set chmod 0444/0555 (`datasets.py`, `runner.py`, daily/sector/weekly research). POSIX modes do not implement private-user Windows ACLs. `runtime_token` uses 0600 creation. | Preserve immutable-data checksums and read-only protection; document Windows ACL/private local directory expectations. Test fixture cleanup restores write attributes as needed. Do not claim POSIX permission equivalence or introduce a dependency without evidence. |
| P2 | Runtime commands already use `sys.executable`, argument lists and explicit repository cwd; Node launchers use spawn without a shell; application paths use pathlib/fileURLToPath/resolve. | Retain these correct choices. Execute real runtime/worker checks with data directories containing spaces and Unicode. Audit inherited handles and parent pipe lifetime; no global process killing or process-name-based cleanup. |

The execution/accounting engines, completed-bar policy boundary, next-open targets, currencies/timezones, costs, experiment protocols and holdout rules are outside implementation scope. Their existing regression tests remain required.

The cancellation finding is confirmed by the [Python subprocess documentation](https://docs.python.org/3/library/subprocess.html#subprocess.Popen.send_signal): Windows SIGTERM maps to termination. The [SQLite context-manager documentation](https://docs.python.org/3.12/library/sqlite3.html#how-to-use-the-connection-context-manager) confirms that a connection transaction context does not close the connection. Background cancellation also needs a wakeable wait: scheduling a main-thread interrupt alone cannot guarantee prompt return from a blocking call (see [thread interruption](https://docs.python.org/3/library/_thread.html#_thread.interrupt_main)).

## Final verification

The reviewed working-tree changes extend the user's lease work with classified contention errors, handle cleanup and initialization after acquiring the Windows byte lock. All five worker entrypoints share portable one-shot cancellation; watch sleeps wake on EOF and regularly return to Python for pending signals on older Windows interpreters. The runtime adds a bounded cancellation deadline, explicit forced-stop notices, idempotent close and exception-safe bind cleanup. The foreground Node launcher uses a lifetime pipe and Windows-only separate process group while retaining its child reference. Finance and trading use deterministic interpreter discovery with platform-appropriate fallbacks.

Snapshot publication uses unique same-directory temporary files. `fileio.py` pairs Windows delete-sharing readers with `FileRenameInfoEx` replacement using `REPLACE_IF_EXISTS | POSIX_SEMANTICS`; POSIX retains `Path.replace`. Python's usual Windows `MoveFileEx` replacement does not support an open destination even with delete sharing, as described in [CPython issue 46003](https://bugs.python.org/issue46003). The [Windows rename flags](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntifs/ns-ntifs-_file_rename_information) preserve old handles while publishing the new name. Unsupported Windows/filesystem cases fall back to the prior replacement API. External handles that deny replacement still cause bounded failure, retaining the previous destination. Read-only destinations are not overwritten. UTF-8 configuration and snapshot reads no longer depend on the Windows locale. SQLite fixture cleanup closes connections without losing transaction commits; study databases close even if final snapshot saving raises.

Setup/deployment guides now include PowerShell commands, foreground ownership/shutdown, ACL expectations and interrupted-job recovery. The macOS launchd installer is unchanged. `.github/workflows/platform.yml` adds Windows/macOS jobs using Node 24 and Python 3.12; the workflow is source-reviewed and has not run. No application dependencies were added. Changes are uncommitted for review.

### Commands and observed results

Run from the repository root with Node 24 on PATH and the existing Python 3.12 venv. Logs, baseline copies, delegation prompts and independent probes are under ignored `artifacts/trading/windows-review/`.

| Command/check | Final Windows result |
| --- | --- |
| `npm test` | 94 backend and 33 frontend tests pass; no backend skips. Baseline memory cleanup failure resolved. |
| `npm run build` | Pass; React production bundle generated. |
| `.venv/Scripts/python.exe -m unittest discover -s trading_agent/tests -v` | 177 tests pass in 83.54 seconds, including the direct-CLI interrupt regression. Baseline five errors and one failure resolved. |
| `.venv/Scripts/python.exe -m trading_agent demo --start 2026-10-14 --output artifacts/trading/windows-review/final-demo` | Complete synthetic session, 29 fills, no errors. Full metrics, fills and decisions exactly match the recorded baseline. |
| Real process ownership/cancellation/recovery regressions | Pass: cross-process lock contention, close/death recovery, init failures, EOF cancellation, pending interrupts without EOF, partial holdings/report, blocked-worker force stop, active shutdown, occupied-port cleanup and owner crash without replay. |
| Independent five-check runtime probe | Pass: completed demo, cancelled open portfolio, sleeping watch cancellation, authenticated HTTP startup/EOF shutdown, crashed-owner recovery with unchanged snapshot and zero replayed workers. |
| Independent Node launcher termination probe | Pass after Windows process-group correction; durable job stopped with an explicit unavailable-report notice when cancelled before report creation. |
| Independent executable-path probe | Pass using an actual Python interpreter under `python space env/Scripts/python.exe`, invoked as an executable with argument arrays. |
| Independent snapshot stress | 2,000 replacements, 9,587 successful reads, zero writer failures, zero malformed JSON reads and no leftover temporary files in 2.08 seconds. 379 transient read OS errors were treated as unavailable snapshots, not fabricated data. |
| `.venv/Scripts/python.exe -m compileall -q trading_agent deploy/install_service.py` | Pass. |
| `.venv/Scripts/python.exe deploy/install_service.py trading`, parsed with `plistlib` | Valid launchd definition generated on Windows; this does not verify macOS service execution. |
| `git diff --check` | Pass. `_edit.py` matches its original bytes and SHA256 `57d0a795235e62c5dba906f5bc4c018cf526973ecffaa9e55cec7c591a4af5a1`. |

An empty untracked `Communication.md` appeared during the work and was left untouched. Existing user files remain uncommitted, alongside the reviewed changes.

The unbounded raw-reader stress attempt demonstrated that retry alone is insufficient when external readers continuously deny replacement; it was stopped and retained as failed/incomplete evidence. The final stress uses the same snapshot-reader adapter as the runtime and also decodes JSON directly so malformed data cannot be hidden by `_read`'s unavailable-result handling. Separate real Windows tests retain an incompatible raw reader to verify persistent denial and successful retry after release.

### Limits and unverified assumptions

No required Windows check is known to remain failing. This is verification of offline software behavior on Windows 11 x64 / local NTFS, not live trading or provider/model performance. macOS execution, POSIX locking execution, physical console keypresses, hosted CI, fresh dependency installation, Windows service installation, network shares, cloud-synced directories and older Windows/filesystem fallback behavior remain unverified. Console responsiveness is covered by real pending-interrupt and parent-pipe tests; an actual interactive Ctrl+C keypress was not manually performed. Real finance/trading MCP integration used offline fixtures; no live Yahoo request or live Ollama policy run establishes performance or strategy evidence. Existing simulation semantics and holdout restrictions are covered by the full unchanged engine/accounting/protocol tests and the deterministic demo comparison.

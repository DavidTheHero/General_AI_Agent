# Contributing

Thanks for helping improve this assistant! The project is still evolving, so please follow the workflow below to keep changes predictable.

## Development workflow

1. **Set up the environment**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Run the backends locally**
   - FastAPI API: `uvicorn fastapi_app:app --reload --port 2610`
   - Flask UI: `export AGENT_API_URL=http://localhost:2610/query && python flask_app.py`

3. **Write code + tests**
   - Add/modify logic in small, reviewable commits.
   - Keep `python3 -m unittest test` passing.
   - Update docs/README when you change behaviour.

4. **Profile & observe**
   - Every `/query` response returns `latency_ms` and `timings` (per-component averages). Include screenshots or notes when submitting performance changes.

## Pull request checklist

- [ ] Added/updated unit tests alongside code changes.
- [ ] Updated `README.md` (and `ROADMAP.md` if scope changes).
- [ ] Verified lint/format (run `python -m compileall` or your preferred tool).
- [ ] No generated artifacts (`semantic_memory.db`, `__pycache__/`, etc.) are committed.
- [ ] Referenced relevant roadmap item or opened a GitHub issue describing the work.

## Roadmap alignment

Major features (memory revamps, deployment changes, etc.) should be discussed upfront. Use GitHub issues referencing `ROADMAP.md` sections, or open a draft PR to share design ideas before doing large refactors.

We welcome iterative improvements—documentation, profiling, UI polish, test coverage, or new tools. Thanks for contributing!

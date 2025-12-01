from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from agent_runtime import reset_memory_state, run_agent_query, semantic_search

app = FastAPI(title="Assistant Agent API")


class QueryRequest(BaseModel):
    query: str
    metadata: dict | None = None


class MemoryResetRequest(BaseModel):
    session_id: str | None = None


class MemorySearchRequest(BaseModel):
    session_id: str
    query: str
    top_k: int | None = 5


@app.post("/query")
async def query_agent(request: QueryRequest):
    try:
        return run_agent_query(request.query, metadata=request.metadata or {})
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/memory/reset")
async def reset_memory(request: MemoryResetRequest):
    return reset_memory_state(request.session_id)


@app.post("/memory/search")
async def search_memory(request: MemorySearchRequest):
    return semantic_search(
        request.session_id, request.query, top_k=request.top_k or 5
    )

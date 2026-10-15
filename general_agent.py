import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from agent.llm import build_chain, create_chat_model
from agent.planners import StockComparisonPlanner, compute_stock_comparison
from agent.semantic import (
    augment_query_with_context,
    record_semantic_event,
    retrieve_semantic_context,
)
from agent.signatures import (
    AssistantRoutingSignature,
    FollowupIntentSignature,
    GeneralAnswerSignature,
    ToolRefinementSignature,
    list_available_tools_text,
)
from agent.telemetry import TokenUsageTracker, ToolUsageMonitor
from agent.tool_handlers import build_tool_handlers
from agent.utils import extract_days, split_queries
from memory import AgentMemory
from profiling import TimingRecorder
from semantic_memory import SemanticMemoryStore
from tools.finance import FinanceToolError

# Environment variables required for optional tools:
# (All remaining tools now rely on public/free APIs.)

USAGE_MONITOR = ToolUsageMonitor()


@dataclass
class AgentPrediction:
    answer: str
    responses: List[Dict[str, str]]
    metadata: Dict[str, Any]


class AssistantAgent:
    """LangChain agent that can chat generally and call tools when useful."""

    def __init__(
        self,
        monitor: ToolUsageMonitor | None = None,
        token_tracker: TokenUsageTracker | None = None,
        semantic_store: SemanticMemoryStore | None = None,
        model=None,
    ):
        model = model if model is not None else create_chat_model()
        self.router = build_chain(
            model, AssistantRoutingSignature,
            "User query: {query}\nAvailable tools:\n{available_tools}",
        )
        self.general_answer = build_chain(
            model, GeneralAnswerSignature, "User query: {query}"
        )
        self.tool_refiner = build_chain(
            model, ToolRefinementSignature,
            "User query: {query}\nTool evidence: {context}",
        )
        self.monitor = monitor or USAGE_MONITOR
        self.token_tracker = token_tracker or TokenUsageTracker()
        self.memory = AgentMemory()
        self._semantic_matches: List[Dict[str, Any]] = []
        self.semantic_store = semantic_store
        self.session_id = "default"
        self._plan_trace: List[Dict[str, Any]] = []
        self.profiling = TimingRecorder()
        self._planners = [StockComparisonPlanner()]
        self._tool_handlers = build_tool_handlers()
        self._available_tools_text = list_available_tools_text()
        self._followup_intent = build_chain(
            model, FollowupIntentSignature,
            "Previous comparison: {previous_summary}\nUser query: {query}",
        )

    def forward(self, query: str, metadata: Optional[dict] = None) -> AgentPrediction:
        if not query or not query.strip():
            raise ValueError("Query cannot be empty.")
        incoming_metadata = dict(metadata or {})
        self.session_id = self._extract_session_id(incoming_metadata)
        incoming_metadata.pop("session_id", None)
        incoming_metadata.pop("semantic_matches", None)
        self.response_mode = (
            incoming_metadata.pop("response_mode", "natural").lower().strip()
        )
        if self.response_mode not in {"natural", "api"}:
            self.response_mode = "natural"
        self.memory = AgentMemory(incoming_metadata)
        self._semantic_matches = []
        self._plan_trace = []
        self.profiling.reset()

        self.monitor.reset()
        self.token_tracker.reset()
        segments = split_queries(query)
        responses = []
        structured = []
        for segment in segments:
            with self._profile_step("segment_pipeline"):
                answer = self._answer_single_query(segment)
            responses.append(self._format_response(segment, answer))
            structured.append({"query": segment, "answer": answer})

        combined_answer = "\n\n".join(responses)

        enriched_metadata = self.memory.snapshot()
        enriched_metadata["session_id"] = self.session_id
        if self._semantic_matches:
            enriched_metadata["semantic_matches"] = self._semantic_matches
        if self._plan_trace:
            enriched_metadata["plan_trace"] = self._plan_trace
        timings = self.profiling.summary()
        if timings:
            enriched_metadata["timings"] = timings
        return AgentPrediction(
            answer=combined_answer,
            responses=structured,
            metadata=enriched_metadata,
        )

    def _answer_single_query(self, single_query: str) -> str:
        single_query = (single_query or "").strip()
        if not single_query:
            return ""

        with self._profile_step("semantic_lookup"):
            semantic_context = retrieve_semantic_context(
                self.semantic_store, self.session_id, single_query, top_k=3
            )
        if semantic_context:
            self._semantic_matches.append(
                {"query": single_query, "matches": semantic_context}
            )
        routed_query = augment_query_with_context(single_query, semantic_context)

        with self._profile_step("lm_router"):
            decision = self.router.invoke({
                "query": routed_query,
                "available_tools": self._available_tools_text,
            })
        self.token_tracker.log("router", single_query, decision.reasoning)
        tool_choice = (decision.tool_choice or "none").strip().lower()
        followup_answer = self._maybe_answer_stock_followup(single_query)
        if followup_answer and tool_choice not in ("stock_quote",):
            return self._finalize_response(single_query, followup_answer)

        planner_answer = self._run_planners(single_query, decision)
        if planner_answer:
            return self._finalize_response(single_query, planner_answer)

        handler_answer = self._dispatch_tool_handler(tool_choice, single_query, decision)
        if handler_answer is not None:
            return self._finalize_response(single_query, handler_answer)

        if followup_answer:
            return self._finalize_response(single_query, followup_answer)

        fallback_answer = (decision.direct_answer or "").strip()
        if not fallback_answer:
            with self._profile_step("lm_general_answer"):
                general_response = self.general_answer.invoke({"query": single_query}).answer
            self.token_tracker.log("general_answer", single_query, general_response)
            fallback_answer = general_response
        self.monitor.log("direct_response", single_query, "no tool used")

        return self._finalize_response(single_query, fallback_answer)

    def usage_summary(self) -> Dict[str, int]:
        """Return aggregated tool usage counts."""
        return self.monitor.summary()

    def token_usage(self) -> Dict[str, int]:
        """Return aggregate token usage stats."""
        return self.token_tracker.summary()

    def _dispatch_tool_handler(self, tool_choice: str, query: str, decision) -> Optional[str]:
        for handler in self._tool_handlers:
            if handler.matches(tool_choice):
                return handler.handle(self, query, decision, tool_choice)
        return None

    def _run_planners(self, query: str, decision) -> Optional[str]:
        for planner in self._planners:
            plan = planner.maybe_plan(self, query, decision)
            if not plan:
                continue
            result = planner.execute(self, plan, query)
            if not result:
                continue
            reflection = planner.reflect(self, plan, result, query)
            trace_entry = planner.trace(plan, result, reflection)
            self._plan_trace.append(trace_entry)
            answer_text = result.get("answer", "")
            if reflection:
                answer_text = f"{answer_text}\n\nReflection: {reflection}"
            if answer_text:
                return answer_text
        return None

    def _maybe_answer_stock_followup(self, query: str) -> Optional[str]:
        entries = None
        summary_parts = []

        last_comparison = self.memory.last_stock_comparison()
        if last_comparison:
            entries = last_comparison.get("entries") or []
            if len(entries) >= 2:
                summary_parts.append(
                    "; ".join(
                        f"{entry['symbol']} changed {entry['change_pct']:+.2f}% "
                        f"({entry['start']:.2f}->{entry['end']:.2f})"
                        for entry in entries
                    )
                )

        recent_symbols = self.memory.get_recent_stock_symbols()
        if recent_symbols:
            summary_parts.append(
                "Recent symbols: " + ", ".join(recent_symbols[-4:])
            )

        summary = " ".join(summary_parts).strip() or "No prior stock context."
        with self._profile_step("lm_followup_intent"):
            intent = self._followup_intent.invoke({"previous_summary": summary, "query": query})
        decision = (intent.refers_to_stock_comparison or "").strip().lower()
        if not decision.startswith("y"):
            return None

        if entries and len(entries) >= 2:
            best = max(entries, key=lambda entry: entry["change_pct"])
            worst = min(entries, key=lambda entry: entry["change_pct"])
            diff = best["change_pct"] - worst["change_pct"]
            days = last_comparison["days"]
            return (
                f"Over the last {days} days, {best['symbol']} outperformed {worst['symbol']} "
                f"by {diff:.2f} percentage points ({best['change_pct']:+.2f}% vs "
                f"{worst['change_pct']:+.2f}%)."
            )

        if len(recent_symbols) >= 2:
            symbols = list(dict.fromkeys(recent_symbols))[-2:]
            days = extract_days(query, default=7)
            try:
                return self._compare_symbols(symbols, days, query)
            except FinanceToolError as exc:
                return str(exc)

        return None

    def _compare_symbols(self, symbols: List[str], days: int, query: str) -> str:
        result = compute_stock_comparison(self, symbols, days, query)
        return result["summary"]

    def _extract_session_id(self, metadata: Dict[str, Any]) -> str:
        session_id = (
            metadata.get("session_id")
            or metadata.get("conversation_id")
            or metadata.get("session")
        )
        if session_id:
            return str(session_id)
        return "default"

    def _format_response(self, query: str, answer: str) -> str:
        if self.response_mode == "api":
            return answer
        cleaned_query = (query or "").strip()
        if cleaned_query:
            return f"For \"{cleaned_query}\": {answer}"
        return answer

    def _profile_step(self, name: str):
        return self.profiling.track(name)

    def _finalize_response(self, query_text: str, answer_text: str) -> str:
        record_semantic_event(
            self.semantic_store,
            self.session_id,
            "user",
            query_text,
            profile_step=self._profile_step,
        )
        record_semantic_event(
            self.semantic_store,
            self.session_id,
            "assistant",
            answer_text,
            profile_step=self._profile_step,
        )
        return answer_text

    def __call__(self, query: str, metadata: Optional[dict] = None) -> AgentPrediction:
        return self.forward(query, metadata)


if __name__ == "__main__":
    agent = AssistantAgent()
    query = os.environ.get(
        "ASSISTANT_QUERY",
        "what is the sum of 12, 18 and 20? what is the weather in London? get me Tesla stock price and upcoming UK holidays.",
    )
    prediction = agent(query)
    print(prediction.answer)
    print("Usage summary:", agent.usage_summary())
    print("Token usage:", agent.token_usage())

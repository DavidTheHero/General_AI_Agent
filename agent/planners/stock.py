"""Planner for stock comparison tasks."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from tools.finance import FinanceToolError, get_stock_history

from agent.utils import extract_days, extract_stock_symbols


def compute_stock_comparison(
    agent, symbols: List[str], days: int, query: str
) -> Dict[str, Any]:
    entries = []
    for symbol in symbols:
        with agent._profile_step("tool_stock_history"):
            print(f"[AssistantAgent] Calling stock history for '{symbol}'.")
            agent.monitor.log("stock_history", query, f"symbol={symbol}")
            history = get_stock_history(symbol, days=days)["history"]
        start = history[0]["close"]
        end = history[-1]["close"]
        change_pct = ((end - start) / start) * 100 if start else 0
        entries.append(
            {
                "symbol": symbol,
                "start": start,
                "end": end,
                "change_pct": change_pct,
            }
        )
    best = max(entries, key=lambda entry: entry["change_pct"])
    worst = min(entries, key=lambda entry: entry["change_pct"])
    diff = best["change_pct"] - worst["change_pct"]
    agent.memory.remember_stock_comparison(entries, days)
    summaries = [
        f"{entry['symbol']}: {entry['start']:.2f} -> {entry['end']:.2f} "
        f"({entry['change_pct']:+.2f}% over {days}d)"
        for entry in entries
    ]
    summary_text = (
        "Stock comparison:\n- "
        + "\n- ".join(summaries)
        + "\n"
        + (
            f"{best['symbol']} outperformed {worst['symbol']} by {diff:.2f} percentage points "
            f"({best['change_pct']:+.2f}% vs {worst['change_pct']:+.2f}% over {days} days)."
        )
    )
    return {
        "entries": entries,
        "best": best,
        "worst": worst,
        "days": days,
        "summary": summary_text,
    }


class StockComparisonPlanner:
    """Plan/execution logic for comparing multiple stock symbols."""

    name = "stock_compare"

    def maybe_plan(self, agent, query: str, decision) -> Optional[Dict[str, Any]]:
        normalized = (query or "").lower()
        symbols = extract_stock_symbols(
            getattr(decision, "stock_symbol", None), query
        )
        if len(symbols) < 2:
            return None
        tool_choice = (getattr(decision, "tool_choice", "") or "").strip().lower()
        if "compare" not in normalized and tool_choice != "stock_quote":
            return None
        days = extract_days(query, default=7)
        symbols = symbols[:4]
        steps = [
            {
                "action": "fetch_stock_history",
                "symbol": symbol,
                "description": f"Fetch {symbol} history for {days} days",
            }
            for symbol in symbols
        ]
        steps.append(
            {
                "action": "compare",
                "description": "Analyze performance and summarize winner",
            }
        )
        plan = {
            "planner": self.name,
            "goal": f"Compare {', '.join(symbols[:2])}",
            "symbols": symbols,
            "days": days,
            "steps": steps,
        }
        if "remind" in normalized or "watch" in normalized:
            plan["follow_up"] = "reminder"
        return plan

    def execute(self, agent, plan: Dict[str, Any], query: str) -> Optional[Dict[str, Any]]:
        try:
            result = compute_stock_comparison(agent, plan["symbols"], plan["days"], query)
        except FinanceToolError as exc:
            return {"plan_type": self.name, "answer": str(exc), "data": {}}
        return {
            "plan_type": self.name,
            "answer": result["summary"],
            "data": result,
        }

    def reflect(
        self,
        agent,
        plan: Dict[str, Any],
        result: Dict[str, Any],
        query: str,
    ) -> Optional[str]:
        if result.get("plan_type") != self.name:
            return None
        data = result.get("data") or {}
        best = data.get("best")
        if not best:
            return None
        reminder_text = (
            f"Keep an eye on {best['symbol']} after its {best['change_pct']:+.2f}% move."
        )
        agent.memory.add_user_reminder(
            reminder_text,
            {
                "source": self.name,
                "symbols": plan.get("symbols"),
                "days": plan.get("days"),
            },
        )
        return reminder_text

    def trace(
        self,
        plan: Dict[str, Any],
        result: Dict[str, Any],
        reflection: Optional[str],
    ) -> Dict[str, Any]:
        data = result.get("data") or {}
        trace_entry = {
            "planner": self.name,
            "goal": plan.get("goal"),
            "steps": plan.get("steps", []),
            "reflection": reflection,
        }
        if data.get("best") and data.get("worst"):
            trace_entry["outcome"] = {
                "best": data["best"]["symbol"],
                "worst": data["worst"]["symbol"],
                "days": data.get("days"),
            }
        return trace_entry

__all__ = ["StockComparisonPlanner", "compute_stock_comparison"]

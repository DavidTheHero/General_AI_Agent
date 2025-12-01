"""DSPy signatures and tool metadata."""

from __future__ import annotations

import dspy

TOOL_DEFINITIONS = [
    ("weather", "Basic current weather via Open-Meteo."),
    ("topic_summary", "Summaries via Wikipedia REST."),
    ("news", "Tech news via Hacker News search."),
    ("news_api", "General news via Reddit search (public API)."),
    ("calculator", "Safe arithmetic calculator."),
    ("time_now", "Current time for a timezone."),
    ("time_convert", "Convert timestamps between timezones."),
    ("fact_lookup", "DuckDuckGo instant answers / factual lookups."),
    ("stock_quote", "Stock quotes and comparisons via Yahoo Finance."),
    ("crypto_price", "Crypto prices via CoinGecko."),
    ("holiday_lookup", "Public holiday lookup via Nager.Date API."),
    ("fun_activity", "Random activity suggestions."),
    ("fun_joke", "Random jokes."),
    ("none", "Answer directly without using a tool."),
]


def list_available_tools_text() -> str:
    """Return a newline separated catalog of available tool names and descriptions."""
    return "\n".join(f"- {name}: {desc}" for name, desc in TOOL_DEFINITIONS)


class AssistantRoutingSignature(dspy.Signature):
    """Route user queries to the right capability and provide direct answers when possible."""

    query: str = dspy.InputField(desc="User question or command")
    available_tools: str = dspy.InputField(
        desc="List of available tool names and descriptions. Choose from these only."
    )
    tool_choice: str = dspy.OutputField(
        desc="Return exactly one tool name from available_tools (or 'none')."
    )
    location: str = dspy.OutputField(
        desc="City/region for weather questions; empty when not relevant"
    )
    topic: str = dspy.OutputField(
        desc="Topic to summarize when the user requests general information"
    )
    news_query: str = dspy.OutputField(
        desc="Keywords for tech/news lookup when the user requests the latest information"
    )
    news_language: str = dspy.OutputField(
        desc="Language code for international news queries (e.g., en, fr)"
    )
    calculator_expression: str = dspy.OutputField(
        desc="Math expression to compute when using the calculator tool"
    )
    time_timezone: str = dspy.OutputField(
        desc="Timezone for current time requests (e.g., 'Europe/London')"
    )
    convert_timestamp: str = dspy.OutputField(
        desc="ISO timestamp to convert when performing timezone conversions"
    )
    convert_from_timezone: str = dspy.OutputField(
        desc="Source timezone for conversions"
    )
    convert_to_timezone: str = dspy.OutputField(
        desc="Target timezone for conversions"
    )
    fact_topic: str = dspy.OutputField(
        desc="Specific topic for fact lookup or instant answer"
    )
    stock_symbol: str = dspy.OutputField(
        desc="Ticker symbol when retrieving stock quotes"
    )
    crypto_asset: str = dspy.OutputField(
        desc="Cryptocurrency identifier for price lookups"
    )
    crypto_currency: str = dspy.OutputField(
        desc="Fiat currency to compare crypto price against (e.g., USD)"
    )
    holiday_country: str = dspy.OutputField(
        desc="Country code for holiday lookup (e.g., US, GB)"
    )
    holiday_year: str = dspy.OutputField(
        desc="Year for holiday lookup, e.g., 2025"
    )
    holiday_month: str = dspy.OutputField(
        desc="Month number for holiday lookup (optional)"
    )
    fun_preference: str = dspy.OutputField(
        desc="Specify 'activity' or 'joke' when requesting something fun"
    )
    fun_topic: str = dspy.OutputField(
        desc="Optional topic or keyword for fun/joke requests"
    )
    reasoning: str = dspy.OutputField(desc="Brief reasoning behind the decision")
    direct_answer: str = dspy.OutputField(
        desc="Helpful response when no tool call is required"
    )


class GeneralAnswerSignature(dspy.Signature):
    """Fallback signature to provide an answer for non-weather questions."""

    query: str = dspy.InputField()
    answer: str = dspy.OutputField()


class ToolRefinementSignature(dspy.Signature):
    """Refine tool outputs into direct answers that address the query."""

    query: str = dspy.InputField(desc="Original user query")
    context: str = dspy.InputField(desc="Evidence or snippets returned by tools")
    answer: str = dspy.OutputField()


class FollowupIntentSignature(dspy.Signature):
    """Decide whether the new query references the previous stock comparison."""

    previous_summary: str = dspy.InputField(
        desc="Summary of the last stock comparison, if any."
    )
    query: str = dspy.InputField(desc="Current user message.")
    refers_to_stock_comparison: str = dspy.OutputField(
        desc="Yes or No: Does the query reference the last stock comparison?"
    )


__all__ = [
    "AssistantRoutingSignature",
    "GeneralAnswerSignature",
    "ToolRefinementSignature",
    "FollowupIntentSignature",
    "TOOL_DEFINITIONS",
    "list_available_tools_text",
]

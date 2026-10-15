"""LangChain output schemas and tool metadata."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

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


class AssistantRoutingSignature(BaseModel):
    """Route user queries to the right capability and provide direct answers when possible."""

    tool_choice: Literal["weather", "topic_summary", "news", "news_api", "calculator", "time_now", "time_convert", "fact_lookup", "stock_quote", "crypto_price", "holiday_lookup", "fun_activity", "fun_joke", "none"] = Field(default="none",
        description="Return exactly one tool name from available_tools (or 'none')."
    )
    location: str = Field(default="",
        description="City/region for weather questions; empty when not relevant"
    )
    topic: str = Field(default="",
        description="Topic to summarize when the user requests general information"
    )
    news_query: str = Field(default="",
        description="Keywords for tech/news lookup when the user requests the latest information"
    )
    news_language: str = Field(default="",
        description="Language code for international news queries (e.g., en, fr)"
    )
    calculator_expression: str = Field(default="",
        description="Math expression to compute when using the calculator tool"
    )
    time_timezone: str = Field(default="",
        description="Timezone for current time requests (e.g., 'Europe/London')"
    )
    convert_timestamp: str = Field(default="",
        description="ISO timestamp to convert when performing timezone conversions"
    )
    convert_from_timezone: str = Field(default="",
        description="Source timezone for conversions"
    )
    convert_to_timezone: str = Field(default="",
        description="Target timezone for conversions"
    )
    fact_topic: str = Field(default="",
        description="Specific topic for fact lookup or instant answer"
    )
    stock_symbol: str = Field(default="",
        description="Ticker symbol when retrieving stock quotes"
    )
    crypto_asset: str = Field(default="",
        description="Cryptocurrency identifier for price lookups"
    )
    crypto_currency: str = Field(default="",
        description="Fiat currency to compare crypto price against (e.g., USD)"
    )
    holiday_country: str = Field(default="",
        description="Country code for holiday lookup (e.g., US, GB)"
    )
    holiday_year: str = Field(default="",
        description="Year for holiday lookup, e.g., 2025"
    )
    holiday_month: str = Field(default="",
        description="Month number for holiday lookup (optional)"
    )
    fun_preference: str = Field(default="",
        description="Specify 'activity' or 'joke' when requesting something fun"
    )
    fun_topic: str = Field(default="",
        description="Optional topic or keyword for fun/joke requests"
    )
    reasoning: str = Field(default="", description="Brief reasoning behind the decision")
    direct_answer: str = Field(default="",
        description="Helpful response when no tool call is required"
    )


class GeneralAnswerSignature(BaseModel):
    """Provide a helpful, direct answer to the user query."""

    answer: str


class ToolRefinementSignature(BaseModel):
    """Answer the user query using only the supplied tool evidence."""

    answer: str


class FollowupIntentSignature(BaseModel):
    """Decide whether the user query references the previous stock comparison."""

    refers_to_stock_comparison: Literal["Yes", "No"]


__all__ = [
    "AssistantRoutingSignature",
    "GeneralAnswerSignature",
    "ToolRefinementSignature",
    "FollowupIntentSignature",
    "TOOL_DEFINITIONS",
    "list_available_tools_text",
]

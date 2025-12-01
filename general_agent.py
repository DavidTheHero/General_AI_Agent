import datetime as dt
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import dspy

from memory import AgentMemory
from profiling import TimingRecorder
from semantic_memory import SemanticMemoryStore
from tools.calculator import CalculatorError, calculate
from tools.calendar_api import CalendarAPIError, get_holidays
from tools.facts import FactLookupError, get_instant_answer
from tools.finance import (
    FinanceToolError,
    get_crypto_price,
    get_stock_history,
    get_stock_quote,
    lookup_stock_symbols,
)
from tools.fun import FunToolError, get_random_activity, get_random_joke
from tools.info import InfoToolError, get_topic_summary, search_tech_news
from tools.news_api import NewsAPIError, search_news
from tools.time_utils import TimeToolError, convert_time, current_time
from tools.weather import get_current_weather

# Environment variables required for optional tools:
# (All remaining tools now rely on public/free APIs.)


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


def normalize_location_text(location: str) -> str:
    """Remove common instruction prefixes/suffixes the LM might append."""
    cleaned = (location or "").strip()
    for separator in ("\n", "###", "System:", "User:"):
        if separator in cleaned:
            cleaned = cleaned.split(separator)[0].strip()
    return cleaned.strip(",. ")


def split_queries(text: str) -> List[str]:
    """Split a combined prompt into individual questions/statements."""
    if not text:
        return []

    segments = [
        segment.strip(" ,\n")
        for segment in re.split(r"[?!.]+", text)
        if segment.strip(" ,\n")
    ]
    return segments or [text.strip()]


def extract_stock_symbols(raw: str | None, query: str) -> List[str]:
    symbols = []
    seen = set()
    seed = f"{raw or ''} {query}".strip()
    for symbol in lookup_stock_symbols(seed):
        if symbol not in seen:
            seen.add(symbol)
            symbols.append(symbol)
    return symbols


def extract_days(text: str, default: int = 7) -> int:
    match = re.search(r"(\d+)\s*(day|week)", text, re.IGNORECASE)
    if match:
        value = int(match.group(1))
        unit = match.group(2).lower()
        if "week" in unit:
            return value * 7
        return value
    return default


@dataclass
class ToolEvent:
    tool: str
    query: str
    details: str = ""


class ToolUsageMonitor:
    """Collects structured telemetry for tool invocations."""

    def __init__(self):
        self.reset()

    def log(self, tool: str, query: str, details: str = "") -> None:
        event = ToolEvent(tool=tool, query=query, details=details)
        self.history.append(event)
        self.counts[tool] = self.counts.get(tool, 0) + 1

    def summary(self) -> Dict[str, int]:
        return dict(self.counts)

    def reset(self) -> None:
        self.history: List[ToolEvent] = []
        self.counts: Dict[str, int] = {}


USAGE_MONITOR = ToolUsageMonitor()


def estimate_tokens(text: str | None) -> int:
    """Rough heuristic to estimate tokens from text length."""
    if not text:
        return 0
    # Approximate 1 token per 4 characters (common heuristic for English text).
    return max(1, len(text) // 4)


@dataclass
class TokenUsageEntry:
    call_type: str
    prompt_tokens: int
    completion_tokens: int


class TokenUsageTracker:
    """Tracks approximate token usage for each LM call."""

    def __init__(self):
        self.reset()

    def log(self, call_type: str, prompt: str | None, completion: str | None) -> None:
        entry = TokenUsageEntry(
            call_type=call_type,
            prompt_tokens=estimate_tokens(prompt),
            completion_tokens=estimate_tokens(completion),
        )
        self.entries.append(entry)

    def summary(self) -> Dict[str, int]:
        total_prompt = sum(entry.prompt_tokens for entry in self.entries)
        total_completion = sum(entry.completion_tokens for entry in self.entries)
        return {
            "calls": len(self.entries),
            "prompt_tokens": total_prompt,
            "completion_tokens": total_completion,
            "total_tokens": total_prompt + total_completion,
        }

    def last_entries(self, n: int = 5) -> List[TokenUsageEntry]:
        return self.entries[-n:]

    def reset(self) -> None:
        self.entries: List[TokenUsageEntry] = []


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


class AssistantAgent(dspy.Module):
    """Simple DSPy agent that can chat generally and call tools when useful."""

    def __init__(
        self,
        monitor: ToolUsageMonitor | None = None,
        token_tracker: TokenUsageTracker | None = None,
        semantic_store: SemanticMemoryStore | None = None,
    ):
        super().__init__()
        self.router = dspy.ChainOfThought(AssistantRoutingSignature)
        self.general_answer = dspy.ChainOfThought(GeneralAnswerSignature)
        self.tool_refiner = dspy.ChainOfThought(ToolRefinementSignature)
        self.monitor = monitor or USAGE_MONITOR
        self.token_tracker = token_tracker or TokenUsageTracker()
        self.memory = AgentMemory()
        self._semantic_matches: List[Dict[str, Any]] = []
        self.semantic_store = semantic_store
        self.session_id = "default"
        self.profiling = TimingRecorder()
        self._available_tools_text = list_available_tools_text()
        self._followup_intent = dspy.ChainOfThought(FollowupIntentSignature)

    def forward(self, query: str, metadata: Optional[dict] = None) -> dspy.Prediction:
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
        timings = self.profiling.summary()
        if timings:
            enriched_metadata["timings"] = timings
        return dspy.Prediction(
            answer=combined_answer,
            responses=structured,
            metadata=enriched_metadata,
        )

    def _answer_single_query(self, single_query: str) -> str:
        single_query = (single_query or "").strip()
        if not single_query:
            return ""

        with self._profile_step("semantic_lookup"):
            semantic_context = self._retrieve_semantic_context(single_query)
        routed_query = self._augment_query_with_context(single_query, semantic_context)

        with self._profile_step("lm_router"):
            decision = self.router(
                query=routed_query,
                available_tools=self._available_tools_text,
            )
        self.token_tracker.log("router", single_query, decision.reasoning)
        tool_choice = (decision.tool_choice or "none").strip().lower()
        followup_answer = self._maybe_answer_stock_followup(single_query)
        if followup_answer and tool_choice not in ("stock_quote",):
            return self._finalize_response(single_query, followup_answer)

        location_text = normalize_location_text(decision.location or "")
        if tool_choice == "weather" and location_text:
            with self._profile_step("tool_weather"):
                location = location_text
                print(f"[AssistantAgent] Calling weather tool for '{location}'.")
                self.monitor.log("weather", single_query, f"location={location}")
                weather_data = get_current_weather(location)
                location_meta = weather_data["location"]
                weather = weather_data["weather"]
                self.memory.remember_weather(location_meta, weather)

                return self._finalize_response(
                    single_query,
                    (
                        f"It is currently {weather['temperature_c']}°C in {location_meta['name']}, "
                        f"{location_meta['country']} with winds at {weather['windspeed_kmh']} km/h."
                    ),
                )

        if tool_choice == "weather" and not location_text:
            return self._finalize_response(
                single_query,
                "I need a specific city or region to check the weather.",
            )

        topic = (decision.topic or "").strip()
        if tool_choice == "topic_summary" and topic:
            with self._profile_step("tool_topic_summary"):
                try:
                    print(
                        f"[AssistantAgent] Calling topic summary tool for '{topic}'."
                    )
                    self.monitor.log("topic_summary", single_query, f"topic={topic}")
                    summary = get_topic_summary(topic)
                    return self._finalize_response(
                        single_query,
                        (
                            f"{summary['title']}: {summary['extract']} "
                            f"(Learn more: {summary['url']})"
                        ),
                    )
                except InfoToolError as exc:
                    return self._finalize_response(single_query, str(exc))

        if tool_choice == "topic_summary" and not topic:
            return self._finalize_response(
                single_query, "Please tell me which topic you'd like summarized."
            )

        news_query = (decision.news_query or "").strip()
        if tool_choice == "news" and news_query:
            with self._profile_step("tool_news"):
                try:
                    print(f"[AssistantAgent] Calling news tool for '{news_query}'.")
                    self.monitor.log("news", single_query, f"query={news_query}")
                    stories = search_tech_news(news_query, max_results=3)
                    formatted = [
                        f"{item['title']} ({item['url'] or 'link unavailable'})"
                        for item in stories
                    ]
                    return self._finalize_response(
                        single_query, "Latest headlines:\n- " + "\n- ".join(formatted)
                    )
                except InfoToolError as exc:
                    return self._finalize_response(single_query, str(exc))

        if tool_choice == "news" and not news_query:
            return self._finalize_response(
                single_query,
                "Let me know the keywords or company you want news about.",
            )

        if tool_choice == "news_api":
            query = news_query or single_query
            if not query:
                return self._finalize_response(
                    single_query, "Tell me what topic you'd like news about."
                )
            language = (decision.news_language or "en").strip() or "en"
            with self._profile_step("tool_news_api"):
                try:
                    print(
                        f"[AssistantAgent] Calling NewsAPI tool for '{query}' ({language})."
                    )
                    self.monitor.log(
                        "news_api", single_query, f"query={query},lang={language}"
                    )
                    articles = search_news(query, language=language, max_results=5)
                    formatted = [
                        f"{article['title']} - {article['source']} ({article['url']})"
                        for article in articles
                    ]
                    return self._finalize_response(
                        single_query, "Top articles:\n- " + "\n- ".join(formatted)
                    )
                except NewsAPIError as exc:
                    return self._finalize_response(single_query, str(exc))

        expression = (decision.calculator_expression or "").strip()
        if tool_choice == "calculator" and expression:
            with self._profile_step("tool_calculator"):
                try:
                    print(
                        f"[AssistantAgent] Calling calculator tool for '{expression}'."
                    )
                    self.monitor.log(
                        "calculator", single_query, f"expression={expression}"
                    )
                    result = calculate(expression)
                    return self._finalize_response(
                        single_query, f"{expression} = {result}"
                    )
                except CalculatorError as exc:
                    return self._finalize_response(single_query, str(exc))

        if tool_choice == "calculator" and not expression:
            return self._finalize_response(
                single_query, "Provide a math expression for me to calculate."
            )

        if tool_choice == "time_convert":
            convert_value = (decision.convert_timestamp or "").strip()
            if not convert_value:
                return self._finalize_response(
                    single_query, "Please provide the time you'd like to convert."
                )
            with self._profile_step("tool_time_convert"):
                try:
                    print(
                        "[AssistantAgent] Calling time conversion tool for "
                        f"{convert_value}."
                    )
                    self.monitor.log(
                        "time_convert",
                        single_query,
                        f"value={convert_value},from={decision.convert_from_timezone},to={decision.convert_to_timezone}",
                    )
                    details = convert_time(
                        convert_value,
                        (decision.convert_from_timezone or "").strip() or None,
                        (decision.convert_to_timezone or "").strip() or None,
                    )
                    self.memory.remember_time_conversion(details)
                    return self._finalize_response(
                        single_query,
                        (
                            f"{details['converted_display']} "
                            f"(from {details['source_time']})"
                        ),
                    )
                except TimeToolError as exc:
                    return self._finalize_response(single_query, str(exc))

        if tool_choice == "time_now":
            timezone = (decision.time_timezone or "").strip() or None
            with self._profile_step("tool_time_now"):
                try:
                    print(
                        "[AssistantAgent] Calling current time tool "
                        f"for '{timezone or 'UTC'}'."
                    )
                    self.monitor.log(
                        "time_now", single_query, f"timezone={timezone or 'UTC'}"
                    )
                    now = current_time(timezone)
                    self.memory.remember_time_request(now["timezone"], now)
                    return self._finalize_response(
                        single_query,
                        (
                            f"The current time in {now['timezone']} is "
                            f"{now['date']} {now['time']} ({now['weekday']})."
                        ),
                    )
                except TimeToolError as exc:
                    return self._finalize_response(single_query, str(exc))

        if tool_choice == "fact_lookup":
            topic = (decision.fact_topic or decision.topic or single_query).strip()
            if not topic:
                return self._finalize_response(
                    single_query, "Please provide a topic to research."
                )
            with self._profile_step("tool_fact_lookup"):
                try:
                    print(f"[AssistantAgent] Calling fact lookup for '{topic}'.")
                    self.monitor.log("fact_lookup", single_query, f"topic={topic}")
                    fact = get_instant_answer(topic)
                    self.memory.remember_fact(
                        topic,
                        fact.get("answer", ""),
                        fact.get("source"),
                        fact.get("url"),
                    )
                    context = (
                        f"Source: {fact.get('source')}\n"
                        f"URL: {fact.get('url')}\n"
                        f"Snippet: {fact['answer']}"
                    )
                    with self._profile_step("lm_tool_refiner"):
                        refined = self.tool_refiner(
                            query=single_query, context=context
                        ).answer
                    link = f" ({fact['url']})" if fact.get("url") else ""
                    if refined:
                        return self._finalize_response(single_query, f"{refined}{link}")
                    return self._finalize_response(
                        single_query, f"{fact['answer']}{link}"
                    )
                except FactLookupError as exc:
                    return self._finalize_response(single_query, str(exc))

        if tool_choice == "stock_quote":
            symbols = extract_stock_symbols(decision.stock_symbol, single_query)
            if not symbols:
                seen = set()
                recent_symbols = self.memory.get_recent_stock_symbols()
                for symbol in reversed(recent_symbols):
                    if symbol not in seen:
                        seen.add(symbol)
                        symbols.append(symbol)
                    if len(symbols) >= 2:
                        break
                symbols = list(reversed(symbols))
                if not symbols:
                    return self._finalize_response(
                        single_query,
                        "Specify at least one stock ticker or company name.",
                    )
            days = extract_days(single_query, default=7)
            if len(symbols) > 1:
                with self._profile_step("tool_stock_compare"):
                    try:
                        comparison = self._compare_symbols(
                            symbols[:4], days, single_query
                        )
                        return self._finalize_response(single_query, comparison)
                    except FinanceToolError as exc:
                        return self._finalize_response(single_query, str(exc))

            symbol = symbols[0]
            with self._profile_step("tool_stock_quote"):
                try:
                    print(f"[AssistantAgent] Calling stock quote for '{symbol}'.")
                    self.monitor.log("stock_quote", single_query, f"symbol={symbol}")
                    quote = get_stock_quote(symbol)
                    self.memory.remember_stock_quote(symbol)
                    return self._finalize_response(
                        single_query,
                        (
                            f"{quote['symbol']}: {quote['price']} {quote['currency']} "
                            f"(change {quote['change']} / {quote['percent_change']}%)."
                        ),
                    )
                except FinanceToolError as exc:
                    return self._finalize_response(single_query, str(exc))

        if tool_choice == "crypto_price":
            asset = (decision.crypto_asset or "").strip().lower()
            currency = (decision.crypto_currency or "usd").strip().lower() or "usd"
            if not asset:
                return self._finalize_response(
                    single_query, "Which cryptocurrency should I check?"
                )
            with self._profile_step("tool_crypto_price"):
                try:
                    print(
                        f"[AssistantAgent] Calling crypto price for '{asset}' in {currency}."
                    )
                    self.monitor.log(
                        "crypto_price",
                        single_query,
                        f"asset={asset},currency={currency}",
                    )
                    price = get_crypto_price(asset, vs_currency=currency)
                    return self._finalize_response(
                        single_query,
                        (
                            f"{price['coin']} price: {price['price']} {price['vs_currency']} "
                            f"(source: {price['source']})."
                        ),
                    )
                except FinanceToolError as exc:
                    return self._finalize_response(single_query, str(exc))

        if tool_choice == "holiday_lookup":
            country = (decision.holiday_country or "").strip()
            year_text = (decision.holiday_year or "").strip()
            month_text = (decision.holiday_month or "").strip()
            if not country:
                return self._finalize_response(
                    single_query, "Provide a country code for the holiday search."
                )
            try:
                year = int(year_text) if year_text else dt.datetime.utcnow().year
            except ValueError:
                return self._finalize_response(
                    single_query, "Holiday year must be a number."
                )
            month = None
            if month_text:
                try:
                    month = int(month_text)
                except ValueError:
                    return self._finalize_response(
                        single_query, "Holiday month must be a number."
                    )
            with self._profile_step("tool_holiday_lookup"):
                try:
                    print(
                        f"[AssistantAgent] Calling holiday API for {country} ({year})."
                    )
                    self.monitor.log(
                        "holiday_lookup",
                        single_query,
                        f"country={country},year={year},month={month}",
                    )
                    holidays = get_holidays(country, year, month=month)
                    today = dt.datetime.utcnow().date()
                    filtered = []
                    for holiday in holidays:
                        try:
                            holiday_date = dt.date.fromisoformat(holiday["date"])
                        except (ValueError, KeyError):
                            continue
                        if holiday_date >= today:
                            filtered.append((holiday_date, holiday))

                    filtered.sort(key=lambda item: item[0])
                    limited = filtered[:5] or filtered or holidays[:5]
                    formatted = [
                        f"{holiday['date']}: {holiday['name']} ({', '.join(holiday.get('type', []) or [])})"
                        for _, holiday in limited
                    ]
                    message = (
                        "Upcoming holidays:\n- " + "\n- ".join(formatted)
                        if formatted
                        else "No upcoming holidays found."
                    )
                    return self._finalize_response(single_query, message)
                except CalendarAPIError as exc:
                    return self._finalize_response(single_query, str(exc))

        if tool_choice in ("fun_activity", "fun"):
            with self._profile_step("tool_fun_activity"):
                try:
                    print("[AssistantAgent] Calling fun activity tool.")
                    self.monitor.log("fun_activity", single_query, "")
                    activity = get_random_activity()
                    return self._finalize_response(
                        single_query,
                        (
                            f"Try this activity: {activity['activity']} "
                            f"(type: {activity['type']}, participants: {activity['participants']})."
                        ),
                    )
                except FunToolError as exc:
                    return self._finalize_response(single_query, str(exc))

        if tool_choice in ("fun_joke",):
            with self._profile_step("tool_fun_joke"):
                try:
                    print("[AssistantAgent] Calling fun joke tool.")
                    topic = (
                        decision.fun_topic
                        or decision.topic
                        or decision.fact_topic
                        or decision.news_query
                        or single_query
                    ).strip()
                    self.monitor.log("fun_joke", single_query, f"topic={topic}")
                    joke = get_random_joke(topic or None)
                    return self._finalize_response(
                        single_query, f"{joke['category']} joke:\n{joke['joke']}"
                    )
                except FunToolError as exc:
                    return self._finalize_response(single_query, str(exc))

        if followup_answer:
            return self._finalize_response(single_query, followup_answer)

        fallback_answer = (decision.direct_answer or "").strip()
        if not fallback_answer:
            with self._profile_step("lm_general_answer"):
                general_response = self.general_answer(query=single_query).answer
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
            intent = self._followup_intent(previous_summary=summary, query=query)
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
        entries = []
        for symbol in symbols:
            try:
                with self._profile_step("tool_stock_history"):
                    print(f"[AssistantAgent] Calling stock history for '{symbol}'.")
                    self.monitor.log("stock_history", query, f"symbol={symbol}")
                    history = get_stock_history(symbol, days=days)["history"]
            except FinanceToolError as exc:
                raise exc
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
        self.memory.remember_stock_comparison(entries, days)
        summaries = [
            f"{entry['symbol']}: {entry['start']:.2f} -> {entry['end']:.2f} "
            f"({entry['change_pct']:+.2f}% over {days}d)"
            for entry in entries
        ]
        return "Stock comparison:\n- " + "\n- ".join(summaries)

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

    def _retrieve_semantic_context(self, query: str) -> List[Dict[str, Any]]:
        if not self.semantic_store:
            return []
        matches = self.semantic_store.query(self.session_id, query, top_k=3)
        if matches:
            self._semantic_matches.append({"query": query, "matches": matches})
        return matches

    def _augment_query_with_context(
        self, query: str, matches: List[Dict[str, Any]]
    ) -> str:
        if not matches:
            return query
        snippets = []
        for item in matches:
            timestamp = item.get("timestamp")
            if timestamp:
                try:
                    stamp = dt.datetime.fromtimestamp(timestamp).isoformat()
                except (ValueError, OSError):
                    stamp = "previous"
            else:
                stamp = "previous"
            snippets.append(
                f"{item.get('role', 'assistant')} ({stamp}): {item.get('content', '')}"
            )
        context_block = "\n".join(snippets[:3])
        return f"{query}\n\nRelevant prior messages:\n{context_block}"

    def _record_semantic_event(self, role: str, content: str) -> None:
        if not self.semantic_store:
            return
        text = (content or "").strip()
        if not text:
            return
        session_id = self.session_id or "default"
        with self._profile_step("semantic_store_write"):
            self.semantic_store.add_entry(session_id, role, text)

    def _finalize_response(self, query_text: str, answer_text: str) -> str:
        self._record_semantic_event("user", query_text)
        self._record_semantic_event("assistant", answer_text)
        return answer_text

def ensure_lm():
    """Configure DSPy to use a local Ollama model."""
    if dspy.settings.lm is not None:
        return

    model_id = os.environ.get("DSPY_MODEL", "ollama/llama3.1:8b-instruct-q4_K_M")
    ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

    dspy.settings.configure(lm=dspy.LM(model_id, api_base=ollama_host, cache=False))


if __name__ == "__main__":
    ensure_lm()
    agent = AssistantAgent()
    query = os.environ.get(
        "ASSISTANT_QUERY",
        "what is the sum of 12, 18 and 20? what is the weather in London? get me Tesla stock price and upcoming UK holidays.",
    )
    prediction = agent(query)
    print(prediction.answer)
    print("Usage summary:", agent.usage_summary())
    print("Token usage:", agent.token_usage())

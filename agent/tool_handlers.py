"""Tool handler registry for AssistantAgent."""

from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence

from agent.utils import extract_days, extract_stock_symbols, normalize_location_text
from tools.calculator import CalculatorError, calculate
from tools.calendar_api import CalendarAPIError, get_holidays
from tools.facts import FactLookupError, get_instant_answer
from tools.finance import FinanceToolError, get_crypto_price, get_stock_quote
from tools.fun import FunToolError, get_random_activity, get_random_joke
from tools.info import InfoToolError, get_topic_summary, search_tech_news
from tools.news_api import NewsAPIError, search_news
from tools.time_utils import TimeToolError, convert_time, current_time
from tools.weather import get_current_weather

if TYPE_CHECKING:  # pragma: no cover
    from general_agent import AssistantAgent


class ToolHandler(ABC):
    tool_names: Sequence[str] = ()

    def matches(self, tool_choice: str) -> bool:
        if not tool_choice:
            return False
        normalized = tool_choice.strip().lower()
        return normalized in self.tool_names

    @abstractmethod
    def handle(self, agent: "AssistantAgent", query: str, decision, tool_choice: str) -> Optional[str]:
        ...


class WeatherHandler(ToolHandler):
    tool_names = ("weather",)

    def handle(self, agent: "AssistantAgent", query: str, decision, tool_choice: str) -> Optional[str]:
        location_text = normalize_location_text(decision.location or "")
        if not location_text:
            return "I need a specific city or region to check the weather."
        with agent._profile_step("tool_weather"):
            print(f"[AssistantAgent] Calling weather tool for '{location_text}'.")
            agent.monitor.log("weather", query, f"location={location_text}")
            weather_data = get_current_weather(location_text)
            location_meta = weather_data["location"]
            weather = weather_data["weather"]
            agent.memory.remember_weather(location_meta, weather)
            return (
                f"It is currently {weather['temperature_c']}°C in {location_meta['name']}, "
                f"{location_meta['country']} with winds at {weather['windspeed_kmh']} km/h."
            )


class TopicSummaryHandler(ToolHandler):
    tool_names = ("topic_summary",)

    def handle(self, agent: "AssistantAgent", query: str, decision, tool_choice: str) -> Optional[str]:
        topic = (decision.topic or "").strip()
        if not topic:
            return "Please tell me which topic you'd like summarized."
        with agent._profile_step("tool_topic_summary"):
            try:
                print(f"[AssistantAgent] Calling topic summary tool for '{topic}'.")
                agent.monitor.log("topic_summary", query, f"topic={topic}")
                summary = get_topic_summary(topic)
                return f"{summary['title']}: {summary['extract']} (Learn more: {summary['url']})"
            except InfoToolError as exc:
                return str(exc)


class TechNewsHandler(ToolHandler):
    tool_names = ("news",)

    def handle(self, agent: "AssistantAgent", query: str, decision, tool_choice: str) -> Optional[str]:
        news_query = (decision.news_query or "").strip()
        if not news_query:
            return "Let me know the keywords or company you want news about."
        with agent._profile_step("tool_news"):
            try:
                print(f"[AssistantAgent] Calling news tool for '{news_query}'.")
                agent.monitor.log("news", query, f"query={news_query}")
                stories = search_tech_news(news_query, max_results=3)
                formatted = [
                    f"{item['title']} ({item['url'] or 'link unavailable'})"
                    for item in stories
                ]
                return "Latest headlines:\n- " + "\n- ".join(formatted)
            except InfoToolError as exc:
                return str(exc)


class NewsAPIHandler(ToolHandler):
    tool_names = ("news_api",)

    def handle(self, agent: "AssistantAgent", query: str, decision, tool_choice: str) -> Optional[str]:
        news_query = (decision.news_query or "").strip() or query
        if not news_query:
            return "Tell me what topic you'd like news about."
        language = (decision.news_language or "en").strip() or "en"
        with agent._profile_step("tool_news_api"):
            try:
                print(f"[AssistantAgent] Calling NewsAPI tool for '{news_query}' ({language}).")
                agent.monitor.log("news_api", query, f"query={news_query},lang={language}")
                articles = search_news(news_query, language=language, max_results=5)
                formatted = [
                    f"{article['title']} - {article['source']} ({article['url']})"
                    for article in articles
                ]
                return "Top articles:\n- " + "\n- ".join(formatted)
            except NewsAPIError as exc:
                return str(exc)


class CalculatorHandler(ToolHandler):
    tool_names = ("calculator",)

    def handle(self, agent: "AssistantAgent", query: str, decision, tool_choice: str) -> Optional[str]:
        expression = (decision.calculator_expression or "").strip()
        if not expression:
            return "Provide a math expression for me to calculate."
        with agent._profile_step("tool_calculator"):
            try:
                print(f"[AssistantAgent] Calling calculator tool for '{expression}'.")
                agent.monitor.log("calculator", query, f"expression={expression}")
                result = calculate(expression)
                return f"{expression} = {result}"
            except CalculatorError as exc:
                return str(exc)


class TimeConvertHandler(ToolHandler):
    tool_names = ("time_convert",)

    def handle(self, agent: "AssistantAgent", query: str, decision, tool_choice: str) -> Optional[str]:
        convert_value = (decision.convert_timestamp or "").strip()
        if not convert_value:
            return "Please provide the time you'd like to convert."
        with agent._profile_step("tool_time_convert"):
            try:
                print(f"[AssistantAgent] Calling time conversion tool for {convert_value}.")
                agent.monitor.log(
                    "time_convert",
                    query,
                    f"value={convert_value},from={decision.convert_from_timezone},to={decision.convert_to_timezone}",
                )
                details = convert_time(
                    convert_value,
                    (decision.convert_from_timezone or "").strip() or None,
                    (decision.convert_to_timezone or "").strip() or None,
                )
                agent.memory.remember_time_conversion(details)
                return f"{details['converted_display']} (from {details['source_time']})"
            except TimeToolError as exc:
                return str(exc)


class TimeNowHandler(ToolHandler):
    tool_names = ("time_now",)

    def handle(self, agent: "AssistantAgent", query: str, decision, tool_choice: str) -> Optional[str]:
        timezone = (decision.time_timezone or "").strip() or None
        with agent._profile_step("tool_time_now"):
            try:
                print(f"[AssistantAgent] Calling current time tool for '{timezone or 'UTC'}'.")
                agent.monitor.log("time_now", query, f"timezone={timezone or 'UTC'}")
                now = current_time(timezone)
                agent.memory.remember_time_request(now["timezone"], now)
                return f"The current time in {now['timezone']} is {now['date']} {now['time']} ({now['weekday']})."
            except TimeToolError as exc:
                return str(exc)


class FactLookupHandler(ToolHandler):
    tool_names = ("fact_lookup",)

    def handle(self, agent: "AssistantAgent", query: str, decision, tool_choice: str) -> Optional[str]:
        topic = (decision.fact_topic or decision.topic or query).strip()
        if not topic:
            return "Please provide a topic to research."
        with agent._profile_step("tool_fact_lookup"):
            try:
                print(f"[AssistantAgent] Calling fact lookup for '{topic}'.")
                agent.monitor.log("fact_lookup", query, f"topic={topic}")
                fact = get_instant_answer(topic)
                agent.memory.remember_fact(
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
                with agent._profile_step("lm_tool_refiner"):
                    refined = agent.tool_refiner(query=query, context=context).answer
                link = f" ({fact['url']})" if fact.get("url") else ""
                return f"{refined or fact['answer']}{link}"
            except FactLookupError as exc:
                return str(exc)


class StockQuoteHandler(ToolHandler):
    tool_names = ("stock_quote",)

    def handle(self, agent: "AssistantAgent", query: str, decision, tool_choice: str) -> Optional[str]:
        symbols = extract_stock_symbols(decision.stock_symbol, query)
        if not symbols:
            seen = set()
            recent_symbols = agent.memory.get_recent_stock_symbols()
            for symbol in reversed(recent_symbols):
                if symbol not in seen:
                    seen.add(symbol)
                    symbols.append(symbol)
                if len(symbols) >= 2:
                    break
            symbols = list(reversed(symbols))
            if not symbols:
                return "Specify at least one stock ticker or company name."
        days = extract_days(query, default=7)
        if len(symbols) > 1:
            with agent._profile_step("tool_stock_compare"):
                try:
                    comparison = agent._compare_symbols(symbols[:4], days, query)
                    return comparison
                except FinanceToolError as exc:
                    return str(exc)
        symbol = symbols[0]
        with agent._profile_step("tool_stock_quote"):
            try:
                print(f"[AssistantAgent] Calling stock quote for '{symbol}'.")
                agent.monitor.log("stock_quote", query, f"symbol={symbol}")
                quote = get_stock_quote(symbol)
                agent.memory.remember_stock_quote(symbol)
                return (
                    f"{quote['symbol']}: {quote['price']} {quote['currency']} "
                    f"(change {quote['change']} / {quote['percent_change']}%)."
                )
            except FinanceToolError as exc:
                return str(exc)


class CryptoPriceHandler(ToolHandler):
    tool_names = ("crypto_price",)

    def handle(self, agent: "AssistantAgent", query: str, decision, tool_choice: str) -> Optional[str]:
        asset = (decision.crypto_asset or "").strip().lower()
        currency = (decision.crypto_currency or "usd").strip().lower() or "usd"
        if not asset:
            return "Which cryptocurrency should I check?"
        with agent._profile_step("tool_crypto_price"):
            try:
                print(f"[AssistantAgent] Calling crypto price for '{asset}' in {currency}.")
                agent.monitor.log("crypto_price", query, f"asset={asset},currency={currency}")
                price = get_crypto_price(asset, vs_currency=currency)
                return (
                    f"{price['coin']} price: {price['price']} {price['vs_currency']} "
                    f"(source: {price['source']})."
                )
            except FinanceToolError as exc:
                return str(exc)


class HolidayLookupHandler(ToolHandler):
    tool_names = ("holiday_lookup",)

    def handle(self, agent: "AssistantAgent", query: str, decision, tool_choice: str) -> Optional[str]:
        country = (decision.holiday_country or "").strip()
        year_text = (decision.holiday_year or "").strip()
        month_text = (decision.holiday_month or "").strip()
        if not country:
            return "Provide a country code for the holiday search."
        try:
            year = int(year_text) if year_text else dt.datetime.utcnow().year
        except ValueError:
            return "Holiday year must be a number."
        month = None
        if month_text:
            try:
                month = int(month_text)
            except ValueError:
                return "Holiday month must be a number."
        with agent._profile_step("tool_holiday_lookup"):
            try:
                print(f"[AssistantAgent] Calling holiday API for {country} ({year}).")
                agent.monitor.log(
                    "holiday_lookup",
                    query,
                    f"country={country},year={year},month={month}",
                )
                holidays = get_holidays(country, year, month=month)
                today = dt.datetime.utcnow().date()
                filtered: List = []
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
                if not formatted:
                    return "No upcoming holidays found."
                return "Upcoming holidays:\n- " + "\n- ".join(formatted)
            except CalendarAPIError as exc:
                return str(exc)


class FunActivityHandler(ToolHandler):
    tool_names = ("fun_activity", "fun")

    def handle(self, agent: "AssistantAgent", query: str, decision, tool_choice: str) -> Optional[str]:
        with agent._profile_step("tool_fun_activity"):
            try:
                print("[AssistantAgent] Calling fun activity tool.")
                agent.monitor.log("fun_activity", query, "")
                activity = get_random_activity()
                return (
                    f"Try this activity: {activity['activity']} "
                    f"(type: {activity['type']}, participants: {activity['participants']})."
                )
            except FunToolError as exc:
                return str(exc)


class FunJokeHandler(ToolHandler):
    tool_names = ("fun_joke",)

    def handle(self, agent: "AssistantAgent", query: str, decision, tool_choice: str) -> Optional[str]:
        with agent._profile_step("tool_fun_joke"):
            try:
                print("[AssistantAgent] Calling fun joke tool.")
                topic = (
                    decision.fun_topic
                    or decision.topic
                    or decision.fact_topic
                    or decision.news_query
                    or query
                ).strip()
                agent.monitor.log("fun_joke", query, f"topic={topic}")
                joke = get_random_joke(topic or None)
                return f"{joke['category']} joke:\n{joke['joke']}"
            except FunToolError as exc:
                return str(exc)


def build_tool_handlers() -> List[ToolHandler]:
    return [
        WeatherHandler(),
        TopicSummaryHandler(),
        TechNewsHandler(),
        NewsAPIHandler(),
        CalculatorHandler(),
        TimeConvertHandler(),
        TimeNowHandler(),
        FactLookupHandler(),
        StockQuoteHandler(),
        CryptoPriceHandler(),
        HolidayLookupHandler(),
        FunActivityHandler(),
        FunJokeHandler(),
    ]

"""Deterministic executive reports and standalone headless scientific charts."""
from dataclasses import asdict
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from .metrics import equity_curve, performance_metrics


ASSUMPTIONS = [
    "Simulation only: no broker connection or real orders. US-listed USD instruments; long-only whole shares and no borrowing.",
    "Signals use completed bars and target orders fill at the next bar open, including modeled slippage and commissions. Scheduled close liquidation uses the final bar close.",
    "Near-real-time mode is delayed-bar event-time replay, not latency-aware live execution. Provider delay and model latency are not executable fill guarantees.",
    "Requested weights are capped; actual weights drift with prices and costs. No order book, market impact, dividends, taxes or interest are simulated.",
    "Benchmark: equal-weight intraday buy-at-open/sell-at-close, rebalanced each session, with fractional shares and no costs.",
    "Win rate counts profitable sell fills, including partial exits. Profit factor is unavailable without realized losses. Turnover counts both buys and sells relative to initial equity.",
    "Sharpe and volatility use completed daily session returns, 252 sessions/year and zero risk-free return. Fewer than two sessions or zero variance leaves Sharpe unavailable.",
    "Previously processed bars are immutable during polling; later source revisions do not rewrite earlier simulated decisions.",
    "Historical LLM decisions may reflect model training knowledge; historical replay does not establish unbiased investment performance.",
]


def atomic_text(path, content):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _number(value, suffix="", digits=2):
    return "Unavailable" if value is None else f"{value:,.{digits}f}{suffix}"


def _charts(output, sessions, curve, minutes, source):
    data_label = "SYNTHETIC demonstration" if source.startswith("SYNTHETIC") else "Yahoo Finance"
    date_label = f"{sessions[0]['session']} – {sessions[-1]['session']}" if len(sessions) > 1 else sessions[0]["session"] if sessions else "No verified session"
    plt.rcParams.update({"font.family": "DejaVu Sans", "axes.spines.top": False, "axes.spines.right": False,
                         "axes.labelcolor": "#364152", "text.color": "#182230", "axes.edgecolor": "#d0d5dd", "axes.grid": True, "grid.alpha": 0.2})
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True, gridspec_kw={"height_ratios": [2, 1]}, layout="constrained")
    fig.suptitle(f"Portfolio performance | simulated\n{data_label}", fontsize=17, fontweight="bold", x=0.06, ha="left")
    if curve:
        times = pd.to_datetime([row["timestamp"] for row in curve], utc=True)
        axes[0].plot(times, [row["equity"] for row in curve], color="#157f77", label="Strategy, net of costs", linewidth=2)
        axes[0].plot(times, [row["benchmark_equity"] for row in curve], color="#62748e", linestyle="--", label="Cost-free intraday benchmark")
        axes[1].fill_between(times, [row["drawdown"] * 100 for row in curve], 0, color="#d46a61", alpha=0.4)
        axes[0].legend(frameon=False, loc="best")
        axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%m-%d\n%H:%M", tz=ZoneInfo("America/New_York")))
    else:
        axes[0].text(0.5, 0.5, "No verified market observations", transform=axes[0].transAxes, ha="center")
        axes[1].set_xticks([])
    axes[0].set_ylabel("Equity (USD)"); axes[1].set_ylabel("Drawdown (%)"); axes[1].set_xlabel(f"New York exchange-local time | {date_label}")
    fig.savefig(output / "performance.png", dpi=160); plt.close(fig)
    fig, ax = plt.subplots(figsize=(11, 5), layout="constrained")
    ax.set_title(f"{data_label} | price paths and simulated executions", loc="left", fontsize=16, fontweight="bold")
    for session in sessions:
        for symbol, rows in session["prices"].items():
            if not rows:
                continue
            base = rows[0]["Open"]
            times = [min(pd.Timestamp(row["timestamp"]) + pd.Timedelta(minutes=minutes), pd.Timestamp(session["session_close"])) for row in rows]
            ax.plot(times, [(row["Close"] / base - 1) * 100 for row in rows], label=f"{symbol} · {session['session']}", linewidth=1.4)
            for side, marker, color in [("buy", "^", "#147d64"), ("sell", "v", "#bb443d")]:
                fills = [fill for fill in session["fills"] if fill["symbol"] == symbol and fill["side"] == side]
                ax.scatter([pd.Timestamp(fill["timestamp"]) for fill in fills], [(fill["fill_price"] / base - 1) * 100 for fill in fills], marker=marker, color=color, s=35, zorder=3)
    has_prices = any(rows for session in sessions for rows in session["prices"].values())
    if has_prices:
        handles, labels = ax.get_legend_handles_labels()
        if handles: ax.legend(frameon=False, fontsize=8, ncol=2)
    else:
        ax.text(0.5, 0.5, "No verified price observations", transform=ax.transAxes, ha="center")
        ax.set_xticks([])
    ax.set_ylabel("Change from session opening price (%)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d\n%H:%M", tz=ZoneInfo("America/New_York")))
    ax.set_xlabel(f"New York time | {date_label} · ▲ buy / ▼ sell · fills include slippage")
    fig.savefig(output / "executions.png", dpi=160); plt.close(fig)
    fig, ax = plt.subplots(figsize=(10, 4), layout="constrained")
    observed_sessions = [session for session in sessions if session["equity"]]
    pnl = [session["final_equity"] - session["initial_equity"] for session in observed_sessions]
    ax.bar([session["session"] for session in observed_sessions], pnl, width=0.6, color=["#157f77" if value >= 0 else "#c46258" for value in pnl])
    if pnl:
        ax.set_xlim(-0.8, max(0.8, len(pnl) - 0.2))
    else:
        ax.text(0.5, 0.5, "No verified session outcomes", transform=ax.transAxes, ha="center")
        ax.set_xticks([])
    ax.axhline(0, color="#667085", linewidth=0.8)
    ax.set_title(f"{data_label} | session profit and loss, net of costs", loc="left", fontweight="bold"); ax.set_ylabel("USD")
    fig.savefig(output / "daily_pnl.png", dpi=160); plt.close(fig)


def write_report(output, config, sessions, *, mode, source, provenance=None, errors=None, status=None):
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    metrics = performance_metrics(sessions, config.initial_cash)
    curve = equity_curve(sessions)
    errors = errors or []
    status = status or ("complete" if sessions and all(session["finished"] for session in sessions) and not errors else "partial")
    if status == "complete" and any(session.get("halt_reason") == "decision_error_limit" for session in sessions):
        status = "policy_halted"
    record = {"generated_at": datetime.now(timezone.utc).isoformat(), "status": status, "mode": mode, "source": source,
              "config": config.model_dump(), "metrics": metrics, "sessions": sessions, "provenance": provenance or [], "errors": errors, "assumptions": ASSUMPTIONS}
    atomic_text(output / "report.json", json.dumps(record, indent=2, allow_nan=False))
    pd.DataFrame(curve).to_csv(output / "equity.csv", index=False)
    fills = [fill for session in sessions for fill in session["fills"]]
    pd.DataFrame(fills, columns=["timestamp", "symbol", "side", "quantity", "reference_price", "fill_price", "commission", "slippage_cost", "realized_pnl", "reason"]).to_csv(output / "fills.csv", index=False)
    atomic_text(output / "decisions.json", json.dumps([{**decision, "session": session["session"]} for session in sessions for decision in session["decisions"]], indent=2, allow_nan=False))
    _charts(output, sessions, curve, config.minutes, source)
    if metrics["final_equity"] is None:
        narrative = "No verified market observations were processed. Performance was not evaluated."
    else:
        comparison = metrics["return_pct"] - metrics["benchmark_return_pct"]
        narrative = (f"The {', '.join(sorted({session.get('policy_name', config.strategy.kind) for session in sessions}))} policy ended with USD {_number(metrics['final_equity'])}, a net change of USD {_number(metrics['net_pnl'])} "
                     f"({_number(metrics['return_pct'])}%). It {'outperformed' if comparison >= 0 else 'underperformed'} the cost-free intraday benchmark by "
                     f"{_number(abs(comparison))} percentage points. Maximum observed drawdown was {_number(metrics['max_drawdown_pct'])}%. "
                     f"Modeled direct costs totaled USD {_number(metrics['commission_cost'] + metrics['slippage_cost'])} across {metrics['fills']} fills. "
                     f"{metrics['completed_sessions']} of {metrics['reported_sessions']} reported sessions reached their scheduled close.")
    if metrics["decision_errors"]:
        narrative += f" {metrics['decision_errors']} policy decisions failed; inspect the decision log and halt reasons."
    cards = [("Net return", _number(metrics["return_pct"], "%")), ("Net P&L", _number(metrics["net_pnl"], " USD")),
             ("Maximum drawdown", _number(metrics["max_drawdown_pct"], "%")), ("Average exposure", _number(metrics["average_exposure_pct"], "%")),
             ("Closed-fill win rate", _number(metrics["closed_fill_win_rate_pct"], "%")), ("Daily Sharpe", _number(metrics["daily_sharpe_zero_risk_free"]))]
    rows = "".join(f"<tr><td>{escape(session['session'])}</td><td>{escape(session['status'])}</td><td>{_number(session['final_equity'] - session['initial_equity']) if session['equity'] else 'Unavailable'}</td><td>{len(session['fills'])}</td><td>{escape(session.get('halt_reason') or '—')}</td></tr>" for session in sessions)
    warning = "".join(f"<li>{escape(str(error))}</li>" for error in errors)
    assumptions = "".join(f"<li>{escape(item)}</li>" for item in ASSUMPTIONS)
    cards_html = "".join(f"<div><span>{escape(label)}</span><strong>{escape(value)}</strong></div>" for label, value in cards)
    html = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Executive Performance Report</title>
<style>body{{font:15px/1.65 system-ui,sans-serif;color:#243247;background:#f3f5f7;margin:0}}main{{max-width:1120px;margin:auto;padding:40px 28px}}h1{{font-size:36px;letter-spacing:-1px;line-height:1.2}}h2{{font-size:22px;margin-top:34px}}.kicker{{color:#157f77;font-size:12px;letter-spacing:2px;text-transform:uppercase}}.meta{{color:#667085;font-size:13px}}.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}}.cards>div{{padding:20px;background:white;border:1px solid #dde3e9;border-radius:10px}}.cards span{{display:block;color:#667085;font-size:12px}}strong{{font-size:24px}}img{{display:block;width:100%;height:auto;background:white;border:1px solid #dde3e9;border-radius:10px;margin:20px 0}}table{{width:100%;border-collapse:collapse;background:white}}td,th{{padding:12px;text-align:left;border-bottom:1px solid #dde3e9}}.scroll{{overflow:auto}}a{{color:#157f77}}li{{margin:8px 0}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#fff;padding:18px;border-radius:10px}}@media(max-width:600px){{main{{padding:24px 16px}}.cards{{grid-template-columns:repeat(2,1fr)}}h1{{font-size:28px}}}}@media print{{body{{background:white}}main{{padding:0}}img,.cards{{break-inside:avoid}}}}</style></head><body><main>
<div class="kicker">Autonomous session simulation</div><h1>Executive Performance Report</h1><p class="meta">Status: {escape(status)} · Mode: {escape(mode)} · Currency: USD<br>Source: {escape(source)}<br>Generated: {escape(record['generated_at'])}</p>
<div class="cards">{cards_html}</div><h2>Executive assessment</h2><p>{escape(narrative)}</p>{'<h2>Run limitations and errors</h2><ul>'+warning+'</ul>' if warning else ''}
<img src="performance.png" alt="Net portfolio equity, cost-free benchmark and portfolio drawdown over exchange-local time">
<h2>Session outcomes</h2><div class="scroll"><table><thead><tr><th>Session</th><th>Status</th><th>Net P&amp;L (USD)</th><th>Fills</th><th>Halt reason</th></tr></thead><tbody>{rows}</tbody></table></div>
<img src="executions.png" alt="Normalized price paths with simulated buy and sell execution markers"><img src="daily_pnl.png" alt="Net profit and loss for each reported session">
<h2>Methodology and limits</h2><ul>{assumptions}</ul><h2>Reproducibility</h2><p><a href="report.json">Full run and market observations (JSON)</a> · <a href="equity.csv">Equity ledger (CSV)</a> · <a href="fills.csv">Execution ledger (CSV)</a> · <a href="decisions.json">Decision log (JSON)</a></p>
<details><summary>Validated configuration</summary><pre>{escape(json.dumps(config.model_dump(), indent=2))}</pre></details><details><summary>Data retrieval provenance</summary><pre>{escape(json.dumps(provenance or [], indent=2))}</pre></details></main></body></html>'''
    atomic_text(output / "report.html", html)
    markdown = f"# Executive Performance Report\n\nStatus: {status}  \nMode: {mode}  \nSource: {source}\n\n{narrative}\n\n![Performance](performance.png)\n\n![Executions](executions.png)\n\n![Session P&L](daily_pnl.png)\n\n## Methodology\n\n" + "\n".join(f"- {item}" for item in ASSUMPTIONS)
    if errors:
        markdown += "\n\n## Run limitations and errors\n\n" + "\n".join(f"- {error}" for error in errors)
    atomic_text(output / "report.md", markdown)
    # Polling readers need metrics without repeatedly loading the full audit ledger.
    atomic_text(output / "summary.json", json.dumps({key: record[key] for key in ["status", "generated_at", "source", "metrics", "errors"]}, allow_nan=False))
    return record

import os
import secrets

import requests
from flask import Flask, jsonify, redirect, render_template, request, session, url_for

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret")

AGENT_API_URL = os.environ.get("AGENT_API_URL", "http://localhost:2610/query")


def call_agent_api(payload):
    try:
        response = requests.post(AGENT_API_URL, json=payload, timeout=120)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        return {"error": f"Agent backend request failed: {exc}"}


@app.route("/query", methods=["POST"])
def query_agent():
    payload = request.get_json(force=True, silent=False) or {}
    query = payload.get("query")
    if not query or not isinstance(query, str):
        return jsonify({"error": "Provide a 'query' string in the JSON body."}), 400

    context = payload.get("metadata") or {}
    return jsonify(call_agent_api({"query": query, "metadata": context}))


def _sanitize_context(metadata: dict | None) -> dict:
    metadata = metadata or {}
    metadata.pop("semantic_matches", None)
    metadata.pop("timings", None)
    return metadata


@app.route("/", methods=["GET", "POST"])
def ui():
    conversation = session.get("conversation", [])
    context = session.get("context", {})
    session_id = session.get("session_id") or secrets.token_hex(16)
    session["session_id"] = session_id

    if request.method == "POST":
        query = request.form.get("query", "").strip()
        if query:
            payload_context = dict(context)
            payload_context["session_id"] = session_id
            reply = call_agent_api({"query": query, "metadata": payload_context})
            if isinstance(reply, dict):
                conversation.append({"query": query, "reply": reply.get("answer"), "raw": reply})
                context = _sanitize_context(reply.get("metadata", context))
            else:
                conversation.append(
                    {"query": query, "reply": str(reply), "raw": {"answer": str(reply)}}
                )
            session["conversation"] = conversation
            session["context"] = context
            session["session_id"] = session_id

    return render_template("chat.html", conversation=conversation)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/reset", methods=["POST"])
def reset_chat():
    session.pop("conversation", None)
    session.pop("context", None)
    session.pop("session_id", None)
    return redirect(url_for("ui"))


@app.route("/chat", methods=["POST"])
def chat_message():
    payload = request.get_json(force=True, silent=False) or {}
    query = (payload.get("query") or "").strip()
    if not query:
        return jsonify({"error": "Please enter a question before sending."}), 400

    conversation = session.get("conversation", [])
    context = session.get("context", {})
    session_id = session.get("session_id") or secrets.token_hex(16)
    session["session_id"] = session_id

    payload_context = dict(context)
    payload_context["session_id"] = session_id
    reply = call_agent_api({"query": query, "metadata": payload_context})
    if isinstance(reply, dict):
        entry = {"query": query, "reply": reply.get("answer"), "raw": reply}
        context = _sanitize_context(reply.get("metadata", context))
    else:
        entry = {"query": query, "reply": str(reply), "raw": {"answer": str(reply)}}

    conversation.append(entry)
    session["conversation"] = conversation
    session["context"] = context
    return jsonify({"item": entry})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=2611, debug=True, use_reloader=False)

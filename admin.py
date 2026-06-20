"""
admin.py — Thunder Control Center
Flask API server สำหรับ dashboard ควบคุมบอท

รัน: python3 admin.py
เปิด browser: http://localhost:8765
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, jsonify, request, send_file

import d1
import sheets
import gpt
from handlers import _kb_matches

app = Flask(__name__)


# ──────────────────────────────────────────────
# Helper: run async coroutine from sync Flask route
# ──────────────────────────────────────────────

def _run(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@app.after_request
def cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,DELETE,OPTIONS"
    return resp


# ──────────────────────────────────────────────
# Serve dashboard HTML
# ──────────────────────────────────────────────

@app.route("/")
def index():
    html_path = os.path.join(os.path.dirname(__file__), "dashboard.html")
    return send_file(html_path)


# ──────────────────────────────────────────────
# Knowledge Base
# ──────────────────────────────────────────────

@app.route("/api/knowledge", methods=["GET", "OPTIONS"])
def list_knowledge():
    if request.method == "OPTIONS":
        return "", 200
    try:
        docs = _run(d1.get_all_knowledge())
        for doc in docs:
            doc["has_image"] = bool(doc.get("image_b64"))
            doc.pop("image_b64", None)
        return jsonify(docs)
    except Exception as e:
        print(f"[ERROR] /api/knowledge: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/knowledge", methods=["POST"])
def add_knowledge():
    data = request.json or {}
    doc_id = _run(d1.save_knowledge(
        content=data.get("content", ""),
        image_b64=data.get("image_b64", ""),
        added_by=data.get("added_by", "dashboard"),
    ))
    return jsonify({"id": doc_id})


@app.route("/api/knowledge/<int:doc_id>", methods=["DELETE", "OPTIONS"])
def delete_knowledge(doc_id):
    if request.method == "OPTIONS":
        return "", 200
    ok = _run(d1.delete_knowledge(doc_id))
    return jsonify({"ok": ok})


# ──────────────────────────────────────────────
# Expiry
# ──────────────────────────────────────────────

@app.route("/api/expiry", methods=["GET"])
def get_expiry():
    q = request.args.get("q", "เดือนนี้")
    try:
        rows = sheets.parse_expiry_query(q)
        return jsonify(rows)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ──────────────────────────────────────────────
# Conversation History
# ──────────────────────────────────────────────

@app.route("/api/history/<chat_id>", methods=["GET"])
def get_history(chat_id):
    history = _run(d1.get_history(chat_id))
    return jsonify(history)


@app.route("/api/history/<chat_id>", methods=["DELETE", "OPTIONS"])
def clear_history(chat_id):
    if request.method == "OPTIONS":
        return "", 200
    _run(d1.clear_history(chat_id))
    return jsonify({"ok": True})


# ──────────────────────────────────────────────
# User Profiles (จำบุคคล)
# ──────────────────────────────────────────────

@app.route("/api/users", methods=["GET", "OPTIONS"])
def list_users():
    if request.method == "OPTIONS":
        return "", 200
    return jsonify(_run(d1.get_all_users()))


@app.route("/api/users", methods=["POST"])
def save_user():
    data = request.json or {}
    chat_id = str(data.get("chat_id", "")).strip()
    if not chat_id:
        return jsonify({"error": "chat_id required"}), 400
    _run(d1.save_user(
        chat_id=chat_id,
        name=data.get("name", ""),
        role=data.get("role", ""),
        notes=data.get("notes", ""),
    ))
    return jsonify({"ok": True})


@app.route("/api/users/<chat_id>", methods=["DELETE", "OPTIONS"])
def delete_user(chat_id):
    if request.method == "OPTIONS":
        return "", 200
    ok = _run(d1.delete_user(chat_id))
    return jsonify({"ok": ok})


# ──────────────────────────────────────────────
# Test Bot (KB-first, same logic as route_message)
# ──────────────────────────────────────────────

@app.route("/api/query", methods=["POST", "OPTIONS"])
def test_query():
    if request.method == "OPTIONS":
        return "", 200
    data = request.json or {}
    question = data.get("question", "").strip()
    if not question:
        return jsonify({"error": "no question"}), 400

    all_kb = _run(d1.get_all_knowledge())
    matched = [doc for doc in all_kb if _kb_matches(question, doc.get("content", ""))]

    if matched:
        parts = [doc.get("content", "").strip() for doc in matched if doc.get("content", "").strip()]
        images = [doc.get("image_b64", "") for doc in matched if doc.get("image_b64")]
        answer = "\n\n".join(parts)
        return jsonify({
            "answer": answer,
            "mode": "verbatim",
            "kb_hit": True,
            "has_image": bool(images),
        })
    else:
        answer = _run(gpt.answer_query(question, all_kb))
        return jsonify({
            "answer": answer,
            "mode": "gpt",
            "kb_hit": False,
            "has_image": False,
        })


# ──────────────────────────────────────────────
# Start
# ──────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "═" * 52)
    print("  ⚡ Thunder Control Center starting...")
    print("  Initializing D1 tables...")
    try:
        _run(d1.init_table())
        print("  D1 tables OK")
    except Exception as e:
        print(f"  WARNING: D1 init failed: {e}")
    print("  Dashboard: http://localhost:8765")
    print("═" * 52 + "\n")
    app.run(port=8765, debug=False, host="0.0.0.0")

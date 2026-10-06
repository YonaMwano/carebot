from __future__ import annotations

import os
import re
import sys
from collections import defaultdict
from typing import Any

from flask import Flask, jsonify, render_template, request
from groq import Groq

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "carebot-secret-key")
app.config["JSON_SORT_KEYS"] = False
app.config["JSONIFY_PRETTYPRINT_REGULAR"] = False

# Debug output
print("=" * 70, file=sys.stderr)
print("CareBot - Environment Debug", file=sys.stderr)
print("=" * 70, file=sys.stderr)

# Print all environment variables that contain API or GROQ
for key, value in os.environ.items():
    if "GROQ" in key.upper() or "API" in key.upper():
        if value:
            print(
                f"✓ {key}: {value[:50]}..." if len(value) > 50 else f"✓ {key}: {value}",
                file=sys.stderr,
            )
        else:
            print(f"✗ {key}: (empty)", file=sys.stderr)

print("=" * 70, file=sys.stderr)

# Get environment variables - with fallback for Vercel
# Strip whitespace/newlines that sometimes appear when pasting into Vercel dashboard
_raw_key = os.getenv("GROQ_API_KEY") or os.getenv("groq_api_key") or ""
GROQ_API_KEY = _raw_key.strip() if _raw_key else None
MODEL_NAME = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

print(
    f"\n[INIT] GROQ_API_KEY set: {bool(GROQ_API_KEY)}  length: {len(GROQ_API_KEY) if GROQ_API_KEY else 0}",
    file=sys.stderr,
)
print(f"[INIT] GROQ_MODEL: {MODEL_NAME}", file=sys.stderr)

# Client is created lazily on first request (more reliable on Vercel serverless)
client = None
_client_error: str | None = None


def get_groq_client() -> Groq | None:
    """Lazy-create the Groq client. Returns None and stores the error if creation fails."""
    global client, _client_error

    if client is not None:
        return client

    if not GROQ_API_KEY:
        _client_error = "GROQ_API_KEY environment variable is missing or empty"
        print(f"[CLIENT] ✗ {_client_error}", file=sys.stderr)
        return None

    try:
        print(f"[CLIENT] Creating Groq client (key length={len(GROQ_API_KEY)})", file=sys.stderr)
        client = Groq(api_key=GROQ_API_KEY)
        _client_error = None
        print("[CLIENT] ✓ Groq client created successfully", file=sys.stderr)
        return client
    except Exception as e:
        _client_error = f"{type(e).__name__}: {e}"
        print(f"[CLIENT] ✗ Client creation failed: {_client_error}", file=sys.stderr)
        import traceback

        traceback.print_exc(file=sys.stderr)
        client = None
        return None


print("=" * 70, file=sys.stderr)

SYSTEM_PROMPT = """You are CareBot, a safe medical assistant for general health information and symptom guidance.

Your responsibilities:
- Offer general, non-diagnostic health information.
- Help with symptom triage and suggest what steps a patient can take at home when appropriate.
- Recommend only common over-the-counter (OTC) items when safe and relevant, such as Paracetamol, Ibuprofen, ORS, antacids, saline nasal spray, hydration, rest, and basic comfort measures.
- Encourage seeing a licensed doctor or pharmacist for persistent, worsening, or unclear symptoms.
- If symptoms suggest an emergency, tell the user to seek urgent medical care immediately.

Critical rules:
- Never diagnose conditions or claim certainty.
- Never prescribe prescription-only medicines or provide exact dosages.
- Never suggest antibiotics, opioids, steroids, controlled substances, or other restricted medications.
- Never say a symptom is definitely one condition without caution.
- Always include a clear disclaimer in your final answer that this is general information, not medical advice.
- Always ask the user to seek care from a real doctor or healthcare professional if symptoms are severe, persistent, worsening, or concerning.
- If the user mentions chest pain, breathing trouble, severe bleeding, fainting, confusion, stroke signs, seizures, severe allergic reaction, severe dehydration, or suicidal thoughts, tell them to seek emergency care immediately.

Your tone should be warm, reassuring, professional, and easy to understand. Keep answers concise but supportive.
"""

EMERGENCY_KEYWORDS = [
    "chest pain",
    "can't breathe",
    "cant breathe",
    "shortness of breath",
    "difficulty breathing",
    "severe bleeding",
    "unconscious",
    "fainting",
    "stroke",
    "seizure",
    "suicidal",
    "severe allergic reaction",
    "anaphylaxis",
    "confusion",
    "severe dehydration",
    "unable to drink",
    "severe abdominal pain",
    "passing out",
    "loss of consciousness",
]

BANNED_DRUG_PATTERNS = [
    "antibiotic",
    "amoxicillin",
    "azithromycin",
    "ciprofloxacin",
    "penicillin",
    "opioid",
    "morphine",
    "codeine",
    "fentanyl",
    "oxycodone",
    "hydrocodone",
    "prednisone",
    "steroid",
    "benzodiazepine",
    "alprazolam",
    "diazepam",
    "lorazepam",
    "prescription medicine",
    " prescription ",
]

SESSION_HISTORY: dict[str, list[dict[str, str]]] = defaultdict(list)


def emergency_detected(text: str) -> bool:
    normalized = text.lower()
    return any(keyword in normalized for keyword in EMERGENCY_KEYWORDS)


def contains_banned_drug(text: str) -> bool:
    normalized = text.lower()
    return any(pattern in normalized for pattern in BANNED_DRUG_PATTERNS)


def strip_exact_dosage(text: str) -> str:
    text = re.sub(
        r"\b\d+\s*(mg|mcg|g|ml)\b", "[dose omitted for safety]", text, flags=re.IGNORECASE
    )
    text = re.sub(
        r"\b\d+\s*(times\s+a\s+day|daily|every\s+\d+\s+hours|per\s+day|tablets?\s+per\s+day)\b",
        "as directed by a clinician",
        text,
        flags=re.IGNORECASE,
    )
    return text


def add_disclaimer(text: str) -> str:
    disclaimer = (
        "\n\nDisclaimer: This is general health information and not a diagnosis or medical advice. "
        "Please consult a licensed doctor, pharmacist, or urgent care professional before taking any medicine, "
        "especially if you are pregnant, breastfeeding, have other health conditions, or are on other medications."
    )
    if "Disclaimer:" in text:
        return text
    return text.rstrip() + disclaimer


def sanitize_reply(reply: str, user_message: str) -> str:
    cleaned = strip_exact_dosage(reply)

    if emergency_detected(user_message):
        return (
            "This may be a medical emergency. Please call emergency services or go to the nearest emergency department "
            "immediately. If you are alone, ask someone nearby to help you and do not delay care.\n\n"
            "Disclaimer: This is general health information and not a diagnosis or medical advice. "
            "Emergency symptoms need urgent medical evaluation."
        )

    if contains_banned_drug(cleaned):
        cleaned = (
            "I can provide general, safe guidance and only common over-the-counter options when appropriate. "
            "I cannot recommend prescription-only medicines or exact doses. "
            "For any medication questions, please speak to a clinician or pharmacist."
        )

    cleaned = cleaned.strip()
    cleaned = add_disclaimer(cleaned)

    if (
        "doctor" not in cleaned.lower()
        and "urgent care" not in cleaned.lower()
        and "consult" not in cleaned.lower()
    ):
        cleaned += "\n\nIf symptoms worsen, last more than a few days, or you have any concern, speak with a licensed doctor or healthcare professional."

    return cleaned


def generate_response(user_message: str, history: list[dict[str, str]]) -> str:
    if not user_message.strip():
        return "Please tell me what symptoms you're experiencing so I can help with general advice and safety guidance."

    if emergency_detected(user_message):
        return sanitize_reply(
            "This may be a medical emergency and should be assessed urgently. Please seek emergency care now.",
            user_message,
        )

    groq_client = get_groq_client()
    if not groq_client:
        print(f"[ERROR] Groq client unavailable. Reason: {_client_error}", file=sys.stderr)
        return (
            "⚠️ The medical AI service is temporarily unavailable. "
            "Please refresh the page and try again. If the problem persists, "
            "the server administrator needs to verify the API configuration."
        )

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Add conversation history
    for item in history[-8:]:
        if "user" in item and "assistant" in item:
            messages.append({"role": "user", "content": item["user"]})
            messages.append({"role": "assistant", "content": item["assistant"]})

    messages.append({"role": "user", "content": user_message})

    try:
        print(f"[API] Calling Groq API: {MODEL_NAME}", file=sys.stderr)
        completion = groq_client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            temperature=0.5,
            max_tokens=450,
        )

        reply = completion.choices[0].message.content.strip()
        print(f"[API] ✓ Response received ({len(reply)} chars)", file=sys.stderr)
        return sanitize_reply(reply, user_message)
    except Exception as e:
        print(f"[ERROR] Groq API call failed: {type(e).__name__}: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc(file=sys.stderr)
        return f"Sorry, I encountered an error: {str(e)}. Please try again in a moment."


@app.route("/", methods=["GET"])
def home() -> str:
    print("[REQUEST] GET /", file=sys.stderr)
    return render_template("index.html")


@app.route("/api/health", methods=["GET"])
def health() -> Any:
    print("[REQUEST] GET /api/health", file=sys.stderr)

    # Force a client creation attempt so health reflects real status
    groq_client = get_groq_client()

    health_data = {
        "status": "ok" if groq_client else "degraded",
        "model": MODEL_NAME,
        "groq_key_set": bool(GROQ_API_KEY),
        "groq_key_length": len(GROQ_API_KEY) if GROQ_API_KEY else 0,
        "client_ready": groq_client is not None,
        "client_error": _client_error,
        "environment": os.getenv("ENVIRONMENT", "production"),
    }

    print(f"[HEALTH] {health_data}", file=sys.stderr)
    return jsonify(health_data)


@app.route("/api/debug", methods=["GET"])
def debug() -> Any:
    """Debug endpoint to check API key status"""
    print("[REQUEST] GET /api/debug", file=sys.stderr)

    groq_client = get_groq_client()
    api_key = GROQ_API_KEY

    debug_info = {
        "groq_api_key_env": bool(os.getenv("GROQ_API_KEY")),
        "groq_api_key_alt_env": bool(os.getenv("groq_api_key")),
        "api_key_available": bool(api_key),
        "api_key_length": len(api_key) if api_key else 0,
        "client_initialized": groq_client is not None,
        "client_error": _client_error,
        "model": MODEL_NAME,
        "python_version": sys.version,
        "groq_installed": True,
    }

    if api_key:
        # Show only a safe preview (first 8 + last 4 chars)
        debug_info["api_key_preview"] = (
            f"{api_key[:8]}...{api_key[-4:]}" if len(api_key) > 12 else "***"
        )

    return jsonify(debug_info)


@app.route("/api/chat", methods=["POST"])
def chat() -> Any:
    print("[REQUEST] POST /api/chat", file=sys.stderr)

    try:
        if not request.is_json:
            print("[ERROR] Request is not JSON", file=sys.stderr)
            return jsonify({"error": "Request must be JSON", "status": "error"}), 400

        payload = request.get_json()
        message = (payload.get("message") or "").strip()
        session_id = payload.get("session_id") or "default-session"

        print(f"[CHAT] Session: {session_id}, Message length: {len(message)}", file=sys.stderr)

        if not message:
            print("[ERROR] Empty message", file=sys.stderr)
            return jsonify({"error": "Please enter a message before sending.", "status": "error"}), 400

        # Critical check – lazy init so we get a real error message
        groq_client = get_groq_client()
        if not groq_client:
            print("[CRITICAL] Client is None! Groq not initialized.", file=sys.stderr)
            print(f"[CRITICAL] GROQ_API_KEY available: {bool(GROQ_API_KEY)}", file=sys.stderr)
            print(f"[CRITICAL] Client error: {_client_error}", file=sys.stderr)
            return jsonify(
                {
                    "error": "❌ API service unavailable. The Groq API client failed to initialize.",
                    "status": "error",
                    "detail": _client_error or "Please refresh the page. If this persists, contact support.",
                }
            ), 503

        history = SESSION_HISTORY.get(session_id, [])
        print(f"[CHAT] History length: {len(history)}", file=sys.stderr)

        reply = generate_response(message, history)

        history.append({"user": message, "assistant": reply})
        if len(history) > 12:
            history = history[-12:]

        SESSION_HISTORY[session_id] = history

        print("[CHAT] ✓ Response sent", file=sys.stderr)
        return jsonify({"reply": reply, "session_id": session_id, "status": "success"}), 200

    except Exception as e:
        print(f"[ERROR] Chat exception: {type(e).__name__}: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc(file=sys.stderr)
        return jsonify({"error": f"Server error: {str(e)}", "status": "error"}), 500


@app.errorhandler(404)
def not_found(error: Any) -> Any:
    return jsonify({"error": "Route not found", "status": "error"}), 404


@app.errorhandler(500)
def server_error(error: Any) -> Any:
    print("[ERROR] 500 Server Error", file=sys.stderr)
    return jsonify({"error": "Internal server error", "status": "error"}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"\n🚀 Starting CareBot on port {port}\n", file=sys.stderr)
    app.run(debug=True, host="0.0.0.0", port=port)
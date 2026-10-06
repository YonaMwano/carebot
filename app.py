from __future__ import annotations

import os
import re
from collections import defaultdict
from typing import Any

from flask import Flask, jsonify, render_template, request
from groq import Groq

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "carebot-secret-key")
app.config["JSON_SORT_KEYS"] = False
app.config["JSONIFY_PRETTYPRINT_REGULAR"] = False

# Get API key from environment
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MODEL_NAME = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

print("=" * 60)
print("CareBot Medical Assistant - Startup")
print("=" * 60)
print(f"[STARTUP] Model: {MODEL_NAME}")
print(f"[STARTUP] API Key Status: {'✓ Present' if GROQ_API_KEY else '✗ Missing'}")

if not GROQ_API_KEY:
    print("[ERROR] GROQ_API_KEY environment variable is not set!")
    print("[ERROR] Please set GROQ_API_KEY in your environment or .env file")
    client = None
else:
    print(f"[STARTUP] API Key (first 20 chars): {GROQ_API_KEY[:20]}...")
    try:
        client = Groq(api_key=GROQ_API_KEY)
        print("[STARTUP] ✓ Groq client initialized successfully")
    except Exception as e:
        print(f"[ERROR] Failed to initialize Groq client: {e}")
        client = None

print("=" * 60)

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
    text = re.sub(r"\b\d+\s*(mg|mcg|g|ml)\b", "[dose omitted for safety]", text, flags=re.IGNORECASE)
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

    if "doctor" not in cleaned.lower() and "urgent care" not in cleaned.lower() and "consult" not in cleaned.lower():
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

    if not client:
        return (
            "The Groq API client is not initialized. Please ensure your GROQ_API_KEY environment variable is set correctly. "
            "Contact the administrator to verify the API key configuration."
        )

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Add conversation history
    for item in history[-8:]:
        if "user" in item and "assistant" in item:
            messages.append({"role": "user", "content": item["user"]})
            messages.append({"role": "assistant", "content": item["assistant"]})

    messages.append({"role": "user", "content": user_message})

    try:
        print(f"[API] Calling Groq API with model: {MODEL_NAME}")
        print(f"[API] Message count: {len(messages)}")
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            temperature=0.5,
            max_tokens=450,
        )

        reply = completion.choices[0].message.content.strip()
        print(f"[API] ✓ Response received: {reply[:50]}...")
        return sanitize_reply(reply, user_message)
    except Exception as e:
        print(f"[ERROR] Groq API Error: {str(e)}")
        error_msg = str(e)
        if "authentication" in error_msg.lower() or "unauthorized" in error_msg.lower():
            return "Authentication error with Groq API. Please check your API key is valid."
        elif "rate" in error_msg.lower():
            return "Groq API rate limit reached. Please try again in a moment."
        else:
            return f"Error connecting to AI service: {error_msg}. Please try again."


@app.route("/", methods=["GET"])
def home() -> str:
    print("[REQUEST] GET /")
    return render_template("index.html")


@app.route("/api/health", methods=["GET"])
def health() -> Any:
    print("[REQUEST] GET /api/health")
    response = {
        "status": "ok",
        "model": MODEL_NAME,
        "api_key_present": bool(GROQ_API_KEY),
        "client_initialized": client is not None,
    }
    return jsonify(response)


@app.route("/api/chat", methods=["POST"])
def chat() -> Any:
    print("[REQUEST] POST /api/chat")

    try:
        # Validate request
        if not request.is_json:
            print("[ERROR] Request is not JSON")
            return jsonify({"error": "Request must be JSON", "status": "error"}), 400

        payload = request.get_json()
        message = (payload.get("message") or "").strip()
        session_id = payload.get("session_id") or "default-session"

        print(f"[CHAT] Session: {session_id}")
        print(f"[CHAT] Message: {message[:50]}...")

        if not message:
            print("[ERROR] Empty message")
            return jsonify({"error": "Please enter a message before sending.", "status": "error"}), 400

        # Get or create session history
        history = SESSION_HISTORY.get(session_id, [])
        print(f"[CHAT] History length: {len(history)}")

        # Generate response
        reply = generate_response(message, history)

        # Add to history
        history.append({"user": message, "assistant": reply})

        # Keep conversation history manageable
        if len(history) > 12:
            history = history[-12:]

        SESSION_HISTORY[session_id] = history

        print(f"[CHAT] ✓ Reply generated. New history length: {len(history)}")

        # Return proper JSON response
        response_data = {
            "reply": reply,
            "session_id": session_id,
            "status": "success"
        }

        print(f"[RESPONSE] ✓ Sending JSON response")
        return jsonify(response_data), 200

    except Exception as e:
        print(f"[ERROR] Exception in /api/chat: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "error": f"Server error: {str(e)}",
            "status": "error"
        }), 500


@app.before_request
def before_request():
    print(f"[REQUEST] {request.method} {request.path}")


@app.errorhandler(404)
def not_found(error: Any) -> Any:
    print(f"[ERROR] 404 Not Found: {request.path}")
    return jsonify({"error": "Route not found", "status": "error"}), 404


@app.errorhandler(500)
def server_error(error: Any) -> Any:
    print(f"[ERROR] 500 Server Error")
    return jsonify({"error": "Internal server error", "status": "error"}), 500


if __name__ == "__main__":
    if not GROQ_API_KEY:
        print("\n⚠️  WARNING: GROQ_API_KEY is not set!")
        print("The app will start but API calls will fail.")
        print("Set GROQ_API_KEY environment variable and restart.")
    
    print("\n🚀 Starting CareBot on http://0.0.0.0:5000")
    print("Press Ctrl+C to stop\n")
    app.run(debug=True, host="0.0.0.0", port=int(os.getenv("PORT", 5000)))

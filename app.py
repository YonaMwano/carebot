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

# Initialize Groq client globally - MUST happen at module load time
print("=" * 60)
print("CareBot - Initializing Groq Client")
print("=" * 60)

# Get environment variables
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
MODEL_NAME = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip()

print(f"[INIT] Model: {MODEL_NAME}")
print(f"[INIT] GROQ_API_KEY length: {len(GROQ_API_KEY)}")
print(f"[INIT] GROQ_API_KEY present: {bool(GROQ_API_KEY)}")

if GROQ_API_KEY:
    print(f"[INIT] API Key (first 30 chars): {GROQ_API_KEY[:30]}...")
    print(f"[INIT] API Key (last 10 chars): ...{GROQ_API_KEY[-10:]}")

# Create global client instance
client = None

if GROQ_API_KEY:
    try:
        print("[INIT] Creating Groq client...")
        client = Groq(api_key=GROQ_API_KEY)
        print("[INIT] ✓ Groq client created successfully")
        
        # Test the connection
        print("[INIT] Testing Groq API connection...")
        test_response = client.models.list()
        print(f"[INIT] ✓ API connection successful - {len(test_response.data)} models available")
    except Exception as e:
        print(f"[INIT] ✗ Failed to initialize Groq client: {e}")
        print(f"[INIT] Exception type: {type(e).__name__}")
        client = None
else:
    print("[INIT] ✗ GROQ_API_KEY is empty or not set!")

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
        print("[ERROR] Client is None in generate_response")
        print(f"[DEBUG] GROQ_API_KEY exists: {bool(GROQ_API_KEY)}")
        print(f"[DEBUG] GROQ_API_KEY length: {len(GROQ_API_KEY) if GROQ_API_KEY else 0}")
        return (
            "The AI service is currently unavailable. Please try again in a few moments. "
            "The API key may not be properly configured on the server."
        )

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Add conversation history
    for item in history[-8:]:
        if "user" in item and "assistant" in item:
            messages.append({"role": "user", "content": item["user"]})
            messages.append({"role": "assistant", "content": item["assistant"]})

    messages.append({"role": "user", "content": user_message})

    try:
        print(f"[API] Calling Groq with model: {MODEL_NAME}")
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            temperature=0.5,
            max_tokens=450,
        )

        reply = completion.choices[0].message.content.strip()
        print(f"[API] ✓ Response received")
        return sanitize_reply(reply, user_message)
    except Exception as e:
        print(f"[ERROR] Groq API call failed: {e}")
        print(f"[ERROR] Exception type: {type(e).__name__}")
        return f"Error: {str(e)}. Please try again in a moment."


@app.route("/", methods=["GET"])
def home() -> str:
    return render_template("index.html")


@app.route("/api/health", methods=["GET"])
def health() -> Any:
    health_status = {
        "status": "ok",
        "model": MODEL_NAME,
        "api_key_present": bool(GROQ_API_KEY),
        "api_key_length": len(GROQ_API_KEY) if GROQ_API_KEY else 0,
        "client_initialized": client is not None,
        "client_type": str(type(client)) if client else "None",
    }
    print(f"[HEALTH] {health_status}")
    return jsonify(health_status)


@app.route("/api/chat", methods=["POST"])
def chat() -> Any:
    try:
        if not request.is_json:
            return jsonify({"error": "Request must be JSON", "status": "error"}), 400

        payload = request.get_json()
        message = (payload.get("message") or "").strip()
        session_id = payload.get("session_id") or "default-session"

        if not message:
            return jsonify({"error": "Please enter a message before sending.", "status": "error"}), 400

        # Check if client is initialized
        if not client:
            print("[CHAT] Client not initialized!")
            return jsonify({
                "error": "API service unavailable. Please refresh and try again.",
                "status": "error",
                "debug": f"Client is None. GROQ_API_KEY set: {bool(GROQ_API_KEY)}"
            }), 503

        history = SESSION_HISTORY.get(session_id, [])
        reply = generate_response(message, history)

        history.append({"user": message, "assistant": reply})
        if len(history) > 12:
            history = history[-12:]

        SESSION_HISTORY[session_id] = history

        return jsonify({
            "reply": reply,
            "session_id": session_id,
            "status": "success"
        }), 200

    except Exception as e:
        print(f"[ERROR] Chat exception: {e}")
        return jsonify({
            "error": f"Server error: {str(e)}",
            "status": "error"
        }), 500


@app.errorhandler(404)
def not_found(error: Any) -> Any:
    return jsonify({"error": "Route not found", "status": "error"}), 404


@app.errorhandler(500)
def server_error(error: Any) -> Any:
    return jsonify({"error": "Internal server error", "status": "error"}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"\n🚀 Starting CareBot on port {port}")
    print(f"Visit: http://localhost:{port}\n")
    app.run(debug=True, host="0.0.0.0", port=port)

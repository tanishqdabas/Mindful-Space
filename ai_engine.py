"""
ai_engine.py — AI & Analysis Engine
MindfulSpace Mental Wellness App

Handles:
  - Gemini API integration with streaming (SSE token-by-token)
  - Maya persona: warm, CBT-grounded, empathetic AI therapist
  - Full conversation history passed on every call (Gemini multi-turn)
  - Session theme summarisation stored per user
  - Sentiment analysis (keyword-based, no external NLP dependency)
  - Risk scoring logic
  - Persona tone response generation (for wellness check-in)
"""

import os
import json
import re
import requests
import logging
from typing import Generator

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# CONFIGURATION
# Set GEMINI_API_KEY as an environment variable before running:
#   export GEMINI_API_KEY="your_key_here"          # Mac / Linux
#   set   GEMINI_API_KEY=your_key_here             # Windows CMD
# ─────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Model: gemini-1.5-flash is fast + free tier; swap to gemini-1.5-pro for richer replies
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")

# Base URL — v1beta supports systemInstruction + multi-turn contents
_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_GENERATE_URL  = f"{_BASE}/{GEMINI_MODEL}:generateContent"
GEMINI_STREAM_URL    = f"{_BASE}/{GEMINI_MODEL}:streamGenerateContent"

# ─────────────────────────────────────────────────────────────
# MAYA — SYSTEM PERSONA (injected as systemInstruction on every call)
# This is the core identity that overrides all other context.
# ─────────────────────────────────────────────────────────────
MAYA_SYSTEM_PROMPT = """You are Maya, a warm, empathetic, and professional AI wellness companion \
built into a college mental health app.

Your therapeutic style:
- You draw on evidence-based techniques from Cognitive Behavioural Therapy (CBT) and mindfulness.
- You listen actively, reflect feelings back using the user's own words, and validate emotions \
  BEFORE offering any perspective or suggestion.
- You ask open-ended questions to gently guide users toward their own clarity (never interrogate).
- You vary your phrasing and sentence structure each reply — never repeat yourself verbatim.
- Keep responses concise: 3–5 sentences unless the user clearly needs more depth.
- Use a calm, grounded tone — warm but not saccharine.

Absolute rules you must never break:
1. You are NOT a medical professional. Never diagnose, never prescribe, never make clinical assessments.
2. Never repeat the same response twice — vary language based on conversation history.
3. If a user expresses suicidal ideation, self-harm, or crisis, respond with compassion and \
   immediately signpost: "Please reach out to a crisis line — in the UK: Samaritans 116 123 \
   (free, 24/7). Your college counselling service is also here for you."
4. Do not generate harmful, offensive, or medically irresponsible content.
5. End every response with either a brief grounding micro-action OR an open question — \
   never both, never neither. Alternate between them naturally across the conversation."""


# ─────────────────────────────────────────────────────────────
# TONE PROMPTS — for wellness check-in card (non-chat context)
# ─────────────────────────────────────────────────────────────
TONE_PROMPTS = {
    "motivational": (
        "You are an uplifting wellness coach. Use energetic, positive, and encouraging language. "
        "Celebrate small wins and inspire the user to keep going with enthusiasm."
    ),
    "constructive": (
        "You are a direct and honest wellness advisor. Provide balanced feedback — acknowledge "
        "progress but clearly point out areas for improvement with practical action steps."
    ),
    "soft": (
        "You are a gentle, empathetic wellness companion. Use warm, nurturing, and compassionate "
        "language. Make the user feel completely safe, heard, and supported without pressure."
    ),
    "strict": (
        "You are a firm accountability coach. Set clear expectations and hold the user to their "
        "commitments. Be disciplined and goal-focused while remaining respectful."
    ),
}

# ─────────────────────────────────────────────────────────────
# SENTIMENT KEYWORDS
# ─────────────────────────────────────────────────────────────
NEGATIVE_KEYWORDS = [
    "sad", "hopeless", "worthless", "hate", "terrible", "awful", "depressed",
    "anxious", "scared", "tired", "exhausted", "lonely", "empty", "numb",
    "angry", "frustrated", "overwhelmed", "stuck", "fail", "failure",
    "can't", "cannot", "never", "always wrong", "no point", "give up",
    "pointless", "meaningless", "broken", "lost", "crying", "tears",
    "hurt", "pain", "suffer", "miserable", "helpless",
]

POSITIVE_KEYWORDS = [
    "happy", "grateful", "great", "amazing", "good", "better", "excited",
    "motivated", "calm", "peaceful", "hopeful", "proud", "accomplished",
    "confident", "loved", "joyful", "energetic", "blessed", "wonderful",
]

# ─────────────────────────────────────────────────────────────
# WELLNESS CHECK SAFETY GUARDRAIL (non-chat prompt)
# ─────────────────────────────────────────────────────────────
SAFETY_GUARDRAIL = (
    "IMPORTANT RULES:\n"
    "1. You are a wellness support tool, NOT a medical professional.\n"
    "2. Never diagnose, prescribe, or make clinical assessments.\n"
    "3. Never encourage harmful behaviour or self-harm.\n"
    "4. If someone seems in crisis, gently suggest professional help.\n"
    "5. Keep responses concise (under 120 words).\n"
)


# ═════════════════════════════════════════════════════════════
# SECTION 1 — SENTIMENT + RISK (unchanged, no external deps)
# ═════════════════════════════════════════════════════════════

def analyze_sentiment(journal_text: str) -> dict:
    """
    Keyword-based sentiment analysis on journal text.

    Returns:
        {
          score:          float  (-1.0 → 1.0),
          label:          str    ('positive' | 'neutral' | 'negative'),
          negative_count: int,
          positive_count: int,
        }
    """
    if not journal_text:
        return {"score": 0.0, "label": "neutral", "negative_count": 0, "positive_count": 0}

    text_lower = journal_text.lower()
    neg_count  = sum(1 for w in NEGATIVE_KEYWORDS if w in text_lower)
    pos_count  = sum(1 for w in POSITIVE_KEYWORDS if w in text_lower)
    total      = neg_count + pos_count

    if total == 0:
        return {"score": 0.0, "label": "neutral", "negative_count": 0, "positive_count": 0}

    score = round((pos_count - neg_count) / total, 2)
    label = "positive" if score > 0.2 else ("negative" if score < -0.2 else "neutral")
    return {"score": score, "label": label, "negative_count": neg_count, "positive_count": pos_count}


def calculate_risk_score(mood: int, sentiment: dict) -> str:
    """
    Wellness risk level: 'Low' | 'Moderate' | 'High'

    Risk points:
      Mood 1-3  → +3   Mood 4-5 → +2   Mood 6-7 → +1   8-10 → 0
      Negative sentiment → +2   Neutral → +1   Positive → 0
    Total 0-1 = Low | 2-3 = Moderate | 4-5 = High
    """
    pts = 0
    if mood <= 3:   pts += 3
    elif mood <= 5: pts += 2
    elif mood <= 7: pts += 1

    s = sentiment.get("label", "neutral")
    if s == "negative":   pts += 2
    elif s == "neutral":  pts += 1

    if pts <= 1:  return "Low"
    if pts <= 3:  return "Moderate"
    return "High"


# ═════════════════════════════════════════════════════════════
# SECTION 2 — GEMINI API HELPERS
# ═════════════════════════════════════════════════════════════

def _api_key_ok() -> bool:
    return bool(GEMINI_API_KEY and GEMINI_API_KEY != "YOUR_GEMINI_API_KEY_HERE")


def _headers() -> dict:
    return {"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY}


def _history_to_contents(history: list) -> list:
    """
    Convert stored chat history list → Gemini `contents` array.

    Each history item is:  { "user": "...", "ai": "..." }
    Gemini expects alternating roles: user → model → user → model …
    """
    contents = []
    for turn in history:
        if turn.get("user"):
            contents.append({
                "role": "user",
                "parts": [{"text": turn["user"]}]
            })
        if turn.get("ai"):
            contents.append({
                "role": "model",
                "parts": [{"text": turn["ai"]}]
            })
    return contents


def _build_maya_payload(history: list, new_message: str, stream: bool = False) -> dict:
    """
    Build the full Gemini API payload for a Maya chat turn.

    - systemInstruction  → Maya persona (injected once, not in history)
    - contents           → full conversation history + new user message
    - generationConfig   → temperature, token limits
    - safetySettings     → block harmful content categories
    """
    # Full history as Gemini contents, then append the new user turn
    contents = _history_to_contents(history)
    contents.append({
        "role": "user",
        "parts": [{"text": new_message}]
    })

    payload = {
        "systemInstruction": {
            "parts": [{"text": MAYA_SYSTEM_PROMPT}]
        },
        "contents": contents,
        "generationConfig": {
            "temperature":     0.82,   # slightly creative but grounded
            "maxOutputTokens": 350,    # ~3-5 sentences
            "topP":            0.92,
            "topK":            40,
        },
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT",        "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH",       "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        ],
    }
    return payload


# ═════════════════════════════════════════════════════════════
# SECTION 3 — STREAMING RESPONSE (SSE)
# ═════════════════════════════════════════════════════════════

def stream_maya_response(history: list, new_message: str) -> Generator[str, None, None]:
    """
    Call Gemini streamGenerateContent and yield SSE-formatted chunks.

    Yields strings in the format:
        data: <token_text>\n\n
        data: [DONE]\n\n

    Each chunk is a partial text token from Gemini's streaming API.
    The caller (Flask route) must set mimetype='text/event-stream'.

    Args:
        history:     list of { user, ai } dicts — full session history
        new_message: the user's latest message string
    """
    if not _api_key_ok():
        yield "data: Hi, I'm Maya 💙 I'm here to support you. What's on your mind today?\n\n"
        yield "data: [DONE]\n\n"
        return

    payload = _build_maya_payload(history, new_message, stream=False)
    url     = f"{GEMINI_GENERATE_URL}"

    try:
        resp = None
        for attempt in range(3):
            r = requests.post(url, headers=_headers(), data=json.dumps(payload), timeout=45)
            if r.status_code == 429:
                import time; time.sleep(3)
                continue
            resp = r
            break

        if resp is None or resp.status_code != 200:
            yield "data: I'm here with you 💙 It sounds like you have something on your mind. Can you tell me more about how you're feeling?\n\n"
            yield "data: [DONE]\n\n"
            return

        try:
            result = resp.json()
            candidates = result.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                full_text = "".join(p.get("text", "") for p in parts).strip()
                if full_text:
                    safe = full_text.replace("\n", "\\n")
                    yield f"data: {safe}\n\n"
                    yield "data: [DONE]\n\n"
                    return
        except Exception as e:
            logger.error(f"[Gemini] Parse error: {e}")

        yield "data: I'm here with you 💙 What would you like to talk about today?\n\n"
        yield "data: [DONE]\n\n"
        return

    except requests.exceptions.Timeout:
        yield "data: \u23f1\ufe0f Maya took too long to respond. Please try again.\n\n"
    except requests.exceptions.ConnectionError:
        yield "data: \ud83d\udd0c Cannot reach Gemini. Check your internet connection.\n\n"
    except Exception as e:
        logger.exception(f"[Gemini Stream] Unexpected error: {e}")
        yield "data: \ud83d\udc99 Something went wrong. You're not alone — please try again.\n\n"

    yield "data: [DONE]\n\n"


# ═════════════════════════════════════════════════════════════
# SECTION 4 — NON-STREAMING RESPONSE (for wellness check-in card)
# ═════════════════════════════════════════════════════════════

def _call_gemini_blocking(payload: dict) -> str:
    """
    Standard (non-streaming) Gemini API call.
    Used for wellness check-in insights where we don't need SSE.

    Returns the response text string, or a safe fallback.
    """
    if not _api_key_ok():
        return (
            "\u26a0\ufe0f Gemini API key not configured. "
            "Set the GEMINI_API_KEY environment variable to enable AI responses."
        )

    url = GEMINI_GENERATE_URL
    try:
        resp = requests.post(
            url,
            headers=_headers(),
            data=json.dumps(payload),
            timeout=20,
        )
        resp.raise_for_status()
        result     = resp.json()
        candidates = result.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            if parts:
                return parts[0].get("text", "").strip()
        return "I'm here for you. Take a deep breath — you're doing great by checking in today. 💙"

    except requests.exceptions.Timeout:
        return "The AI took too long to respond. Please try again in a moment."
    except requests.exceptions.ConnectionError:
        return "Unable to reach the AI service. Please check your internet connection."
    except requests.exceptions.HTTPError as e:
        code = e.response.status_code if e.response else 0
        if code == 400: return "Invalid API request. Please verify your Gemini API key."
        if code == 429: return "AI service is busy right now. Please try again shortly."
        return "AI service returned an error. Please try again."
    except Exception:
        return "Something went wrong. Remember: you're not alone, and help is always available. 💙"


# ═════════════════════════════════════════════════════════════
# SECTION 5 — SESSION THEME SUMMARISER
# ═════════════════════════════════════════════════════════════

def summarise_session(history: list) -> dict:
    """
    At end-of-session, ask Gemini to extract key themes from the conversation.

    Args:
        history: full list of { user, ai } dicts

    Returns:
        {
          themes:  list[str]   — e.g. ["exam stress", "sleep", "self-worth"]
          summary: str         — 1-2 sentence overview
          mood_signal: str     — 'positive' | 'neutral' | 'distressed'
        }
    Falls back gracefully if API call fails.
    """
    if not _api_key_ok() or not history:
        return {"themes": [], "summary": "Session too short to summarise.", "mood_signal": "neutral"}

    # Build a plain-text transcript
    transcript_lines = []
    for i, turn in enumerate(history, 1):
        if turn.get("user"):
            transcript_lines.append(f"User: {turn['user']}")
        if turn.get("ai"):
            transcript_lines.append(f"Maya: {turn['ai']}")
    transcript = "\n".join(transcript_lines[:60])  # cap at 60 lines to stay within tokens

    summariser_prompt = (
        "You are a clinical note assistant. Analyse the following therapy chat transcript "
        "and return ONLY a JSON object (no markdown, no code fences) with these exact keys:\n"
        "  themes       — array of 2-5 short theme strings (e.g. 'exam stress', 'sleep issues')\n"
        "  summary      — 1-2 sentence plain-English overview of what was discussed\n"
        "  mood_signal  — one of: 'positive', 'neutral', 'distressed'\n\n"
        f"TRANSCRIPT:\n{transcript}"
    )

    payload = {
        "contents": [{"role": "user", "parts": [{"text": summariser_prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 250},
    }

    url = GEMINI_GENERATE_URL
    try:
        resp = requests.post(
            url,
            headers=_headers(),
            data=json.dumps(payload),
            timeout=20,
        )
        resp.raise_for_status()
        result = resp.json()
        candidates = result.get("candidates", [])
        if not candidates:
            raise ValueError("No candidates")

        raw_text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")

        # Strip markdown fences if Gemini adds them
        raw_text = re.sub(r"```(?:json)?", "", raw_text).strip().strip("`").strip()

        parsed = json.loads(raw_text)
        return {
            "themes":      parsed.get("themes", []),
            "summary":     parsed.get("summary", ""),
            "mood_signal": parsed.get("mood_signal", "neutral"),
        }

    except Exception as e:
        logger.warning(f"[summarise_session] Failed: {e}")
        return {
            "themes":      [],
            "summary":     "Could not generate summary for this session.",
            "mood_signal": "neutral",
        }


# ═════════════════════════════════════════════════════════════
# SECTION 6 — AGENTIC DISTRESS DETECTION ENGINE
# Runs after every chat message. Analyses the last 3–5 turns
# for crisis signals using:
#   A) Instant keyword triggers  (suicide / self-harm → CRISIS)
#   B) High-risk keyword scoring  (hopeless, worthless … → flag)
#   C) Sentiment threshold        (compound score < -0.6 → flag)
#   D) Persistent low mood        (3+ consecutive flagged turns)
# ═════════════════════════════════════════════════════════════

# ── A) Instant crisis keywords — trigger immediately, no threshold ──
CRISIS_KEYWORDS = [
    "suicide", "suicidal", "kill myself", "end my life", "take my life",
    "want to die", "better off dead", "self-harm", "self harm", "cutting myself",
    "hurt myself", "overdose", "hang myself", "jump off",
]

# ── B) High-risk distress keywords — contribute to scoring ──
DISTRESS_KEYWORDS = [
    "hopeless", "worthless", "can't go on", "cannot go on", "no point",
    "give up", "exhausted", "numb", "alone", "no one cares", "nobody cares",
    "i'm broken", "i am broken", "pointless", "meaningless", "don't want to",
    "can't cope", "cannot cope", "falling apart", "can't breathe",
    "so tired", "done with everything", "given up", "trapped", "invisible",
    "nobody understands", "no reason", "lost everything", "i hate myself",
    "hate myself", "disgusting", "pathetic", "useless", "burden",
    "no future", "no hope", "empty inside", "dead inside",
]

# Sentiment scoring weights for distress detection
_DISTRESS_WEIGHTS = {
    # Each DISTRESS keyword hit = +1 distress point
    # Each NEGATIVE_KEYWORDS hit (from existing list) = +0.5
}


def _sentiment_score_for_detection(text: str) -> float:
    """
    Returns a compound sentiment score in range [-1.0, 1.0].
    Negative = distressed. Uses the existing keyword lists.
    -1.0 = maximally negative, 0 = neutral, +1.0 = maximally positive.
    """
    if not text:
        return 0.0

    lower = text.lower()
    neg   = sum(1 for w in NEGATIVE_KEYWORDS if w in lower)
    pos   = sum(1 for w in POSITIVE_KEYWORDS if w in lower)
    # Extra weight for distress-specific keywords
    neg  += sum(2 for w in DISTRESS_KEYWORDS if w in lower)

    total = neg + pos
    if total == 0:
        return 0.0
    return round((pos - neg) / total, 3)


def run_distress_detection(recent_messages: list, consecutive_low_count: int = 0) -> dict:
    """
    Agentic distress detection — runs after every chat message.

    Args:
        recent_messages:      list of user message strings (last 3–5 turns).
                              The MOST RECENT message must be last.
        consecutive_low_count: how many consecutive turns have already been
                              flagged as moderate (passed in from session state).

    Returns a structured result dict:
    {
      "level":         "none" | "moderate" | "crisis",
      "trigger":       "keyword_crisis" | "keyword_distress" |
                       "sentiment_threshold" | "persistent_low" | None,
      "keywords_found": list[str],        # matched crisis or distress keywords
      "sentiment_score": float,           # score of the latest message
      "consecutive_low": int,             # updated consecutive count
      "icall_number":  "9152987821",      # always present for crisis level
      "message":       str,               # compassionate intervention text
      "should_intervene": bool,           # True when UI should pause chat
    }
    """
    if not recent_messages:
        return _no_flag(consecutive_low_count)

    # ── Combine last 3–5 user messages for analysis ──
    window       = recent_messages[-5:]   # up to last 5 turns
    latest_msg   = recent_messages[-1]    # most recent message only
    combined_text= " ".join(window).lower()
    latest_lower = latest_msg.lower()

    # ────────────────────────────────────────────────
    # CHECK A: Instant Crisis Keywords (zero tolerance)
    # If ANY crisis keyword appears in the LATEST message
    # → immediate CRISIS flag, no threshold needed.
    # ────────────────────────────────────────────────
    crisis_hits = [kw for kw in CRISIS_KEYWORDS if kw in latest_lower]
    if crisis_hits:
        return {
            "level":           "crisis",
            "trigger":         "keyword_crisis",
            "keywords_found":  crisis_hits,
            "sentiment_score": _sentiment_score_for_detection(latest_msg),
            "consecutive_low": consecutive_low_count + 1,
            "icall_number":    "9152987821",
            "should_intervene":True,
            "message": (
                "I want to pause for a moment — what you just shared tells me "
                "you might be carrying something incredibly heavy right now. "
                "You are not alone in this, and your life has value. "
                "Please reach out to a crisis line immediately — "
                "iCall India: 9152987821 (Mon–Sat, 8am–10pm). "
                "Would you like me to help you book an urgent session with one of our therapists right now?"
            ),
        }

    # ────────────────────────────────────────────────
    # CHECK B: High-Risk Distress Keywords
    # Score the combined window for distress vocabulary.
    # 2+ hits across the window → moderate flag candidate.
    # ────────────────────────────────────────────────
    distress_hits = [kw for kw in DISTRESS_KEYWORDS if kw in combined_text]
    distress_score = len(distress_hits)

    # ────────────────────────────────────────────────
    # CHECK C: Sentiment Threshold
    # Compound score of the latest message < -0.6
    # ────────────────────────────────────────────────
    latest_sentiment = _sentiment_score_for_detection(latest_msg)
    sentiment_flagged = latest_sentiment < -0.6

    # ────────────────────────────────────────────────
    # CHECK D: Persistent Low Mood
    # Track consecutive flagged turns passed from session.
    # 3+ in a row → escalate even if individual scores are mild.
    # ────────────────────────────────────────────────
    is_moderate_signal = distress_score >= 2 or sentiment_flagged

    if is_moderate_signal:
        new_consecutive = consecutive_low_count + 1
    else:
        new_consecutive = 0   # reset streak on neutral/positive turn

    # Persistent low = 3+ consecutive moderate signals
    persistent_low = new_consecutive >= 3

    # ────────────────────────────────────────────────
    # DECISION TREE
    # ────────────────────────────────────────────────
    if persistent_low:
        return {
            "level":           "moderate",
            "trigger":         "persistent_low",
            "keywords_found":  distress_hits,
            "sentiment_score": latest_sentiment,
            "consecutive_low": new_consecutive,
            "icall_number":    "9152987821",
            "should_intervene":True,
            "message": (
                "I've noticed that across our conversation you've been describing "
                "things that sound really difficult — and I want to acknowledge that. "
                "It takes courage to keep talking. You don't have to carry this alone. "
                "Would you like me to help you schedule a session with one of our "
                "college therapists or peer supporters? Sometimes talking to a real "
                "person makes all the difference."
            ),
        }

    if distress_score >= 2:
        return {
            "level":           "moderate",
            "trigger":         "keyword_distress",
            "keywords_found":  distress_hits,
            "sentiment_score": latest_sentiment,
            "consecutive_low": new_consecutive,
            "icall_number":    None,
            "should_intervene":True,
            "message": (
                "I've noticed you might be going through something really heavy right now. "
                "What you're feeling is valid, and you deserve support beyond what I can offer. "
                "Would you like me to help you book a session with one of our in-house "
                "therapists or peer supporters? You don't have to face this alone."
            ),
        }

    if sentiment_flagged:
        return {
            "level":           "moderate",
            "trigger":         "sentiment_threshold",
            "keywords_found":  distress_hits,
            "sentiment_score": latest_sentiment,
            "consecutive_low": new_consecutive,
            "icall_number":    None,
            "should_intervene":True,
            "message": (
                "Something in what you've shared tells me you might be in a difficult place "
                "right now. I'm here with you. Would it help to speak with one of our "
                "college therapists or a peer supporter? I can help you find an available slot."
            ),
        }

    # ── No flag ──
    return _no_flag(new_consecutive)


def _no_flag(consecutive_low: int) -> dict:
    """Return a clean 'no distress detected' result."""
    return {
        "level":           "none",
        "trigger":         None,
        "keywords_found":  [],
        "sentiment_score": 0.0,
        "consecutive_low": consecutive_low,
        "icall_number":    None,
        "should_intervene":False,
        "message":         None,
    }


# ═════════════════════════════════════════════════════════════
# SECTION 7 — WELLNESS CHECK-IN RESPONSE (non-streaming, toned)
# ═════════════════════════════════════════════════════════════

def generate_ai_response(
    context: str,
    tone: str,
    mood=None,
    journal=None,
    habits=None,
    risk=None,
    user_message=None,
    history: list = None,
) -> str:
    """
    Public function called by main.py for wellness check-in insight cards.
    Uses a single-turn, non-streaming Gemini call with tone + safety guardrail.

    For live chat, use stream_maya_response() instead.

    Args:
        context:      'wellness_check' | 'chat'
        tone:         one of TONE_PROMPTS keys
        mood:         int 1-10
        journal:      str journal entry
        habits:       list[str] completed habits
        risk:         'Low' | 'Moderate' | 'High'
        user_message: str (chat context only)
        history:      list[dict] (chat context only, passed to Maya)

    Returns:
        AI response string
    """
    tone_instruction = TONE_PROMPTS.get(tone, TONE_PROMPTS["motivational"])

    if context == "wellness_check":
        habit_str       = ", ".join(habits) if habits else "none logged"
        journal_snippet = (journal or "No journal entry.")[:300]
        prompt = (
            f"{SAFETY_GUARDRAIL}\n\n"
            f"TONE INSTRUCTION:\n{tone_instruction}\n\n"
            f"USER WELLNESS CHECK-IN:\n"
            f"- Mood Score: {mood}/10\n"
            f"- Risk Level: {risk}\n"
            f"- Habits Completed: {habit_str}\n"
            f"- Journal (excerpt): {journal_snippet}\n\n"
            f"Provide a brief, personalised wellness insight and one specific action "
            f"the user can take right now. Match your tone to the TONE INSTRUCTION."
        )
    else:
        # Fallback single-turn chat (used if streaming isn't available)
        prompt = (
            f"{SAFETY_GUARDRAIL}\n\n"
            f"TONE INSTRUCTION:\n{tone_instruction}\n\n"
            f"USER MESSAGE: {user_message}\n\n"
            f"Respond as Maya, a warm wellness companion. "
            f"Stay supportive, safe, and match the TONE INSTRUCTION."
        )

    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature":     0.75,
            "maxOutputTokens": 200,
            "topP":            0.9,
        },
    }
    return _call_gemini_blocking(payload)

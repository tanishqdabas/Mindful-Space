"""
main.py — Flask Application Entry Point
MindfulSpace Mental Wellness App

Routes:
  /               → Login
  /dashboard      → Check-In tab
  /chat-page      → AI Chat tab
  /book           → Book Appointment tab (now with live scheduling)
  /chat           → AJAX endpoint for Gemini chat
  /cancel-appointment → Cancel a booking

  ── Live Calendar Routes ──
  /fetch-slots    → AJAX: fetch real-time availability slots
  /create-booking → AJAX: confirm & create calendar event + store metadata
  /cancel-booking → AJAX: cancel a session (Google event + metadata)

  ── Webhook Receivers ──
  /webhook/calendly → Calendly v2 webhook (invitee.created / invitee.canceled)
  /webhook/google   → Google Calendar push notification channel

  ── Google OAuth2 Web Flow (optional) ──
  /gcal-auth      → Redirect to Google consent page
  /gcal-callback  → Handle OAuth2 callback + token exchange

  /logout         → Clear session
"""

from flask import (
    Flask, render_template, request, session,
    redirect, url_for, jsonify, Response, stream_with_context
)
from ai_engine import (
    analyze_sentiment,
    calculate_risk_score,
    generate_ai_response,
    stream_maya_response,
    summarise_session,
    run_distress_detection,          # ← agentic distress detector
)
from calendar_engine import (
    fetch_availability,
    create_booking,
    cancel_session,
    cancel_google_event,
    get_session,
    list_sessions_for_user,
    process_calendly_webhook,
    process_google_webhook,
    get_google_auth_url,
    exchange_google_code,
    register_google_push_channel,
    get_availability_source_label,
    test_calendar_connection,
    send_reminder_notification,
    SESSION_STORE,
)

import os
from dotenv import load_dotenv
load_dotenv()
import time
import logging
from datetime import datetime, timezone

# ── Logging setup ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s"
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY")
if not app.secret_key:
    raise RuntimeError("SECRET_KEY environment variable is not set. See .env.example.")

# ── In-memory user data store ──
# { username: { entries: [], chat_history: [], appointments: [] } }
user_data: dict = {}

# ── Supporter metadata ──
SUPPORTERS = {
    "t1": {"avatar": "👩‍⚕️", "name": "Dr. Sarah Mitchell", "role": "Therapist"},
    "t2": {"avatar": "🧑‍⚕️", "name": "Dr. James Okafor",  "role": "Therapist"},
    "t3": {"avatar": "👩‍⚕️", "name": "Dr. Priya Sharma",  "role": "Therapist"},
    "p1": {"avatar": "🧑‍🎓", "name": "Leo Thompson",       "role": "Peer Supporter"},
    "p2": {"avatar": "👩‍🎓", "name": "Amara Diallo",       "role": "Peer Supporter"},
    "p3": {"avatar": "🧑‍🎓", "name": "Kai Nakamura",       "role": "Peer Supporter"},
}

FORMAT_LABELS = {
    "in-person": "🏛️ In-Person",
    "video":     "📹 Video Call",
    "phone":     "📞 Phone Call",
}

SESSION_TYPE_LABELS = {
    "solo_therapy":       "🧠 Solo Therapy",
    "peer_support_group": "🤝 Peer Support Group",
    "crisis_checkin":     "🚨 Crisis Check-In",
}


# ─────────────────────────────────────────────
# Helper: ensure user record exists
# ─────────────────────────────────────────────
def ensure_user(username: str) -> None:
    if username not in user_data:
        user_data[username] = {
            "entries":              [],
            "chat_history":         [],
            "appointments":         [],   # legacy simple bookings
            "consecutive_low_count": 0,   # distress detection streak counter
        }
    # Back-fill key for existing sessions (safe no-op if already present)
    user_data[username].setdefault("consecutive_low_count", 0)


# ─────────────────────────────────────────────
# ROUTE: Home / Login
# ─────────────────────────────────────────────
@app.route("/", methods=["GET", "POST"])
def index():
    if "username" in session:
        return redirect(url_for("dashboard"))

    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        if not username or len(username) < 2:
            error = "Please enter a valid username (at least 2 characters)."
        else:
            session["username"] = username
            session["tone"]     = "motivational"
            ensure_user(username)
            return redirect(url_for("dashboard"))

    return render_template("index.html", page="login", error=error)


# ─────────────────────────────────────────────
# ROUTE: Dashboard — Check-In Tab
# ─────────────────────────────────────────────
@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    if "username" not in session:
        return redirect(url_for("index"))

    username = session["username"]
    tone     = session.get("tone", "motivational")
    ensure_user(username)
    insight = None

    if request.method == "POST":
        action = request.form.get("action")

        if action == "set_tone":
            tone           = request.form.get("tone", "motivational")
            session["tone"] = tone

        elif action == "submit_entry":
            try:
                mood_score = int(request.form.get("mood", 5))
            except (ValueError, TypeError):
                mood_score = 5
            mood_score = max(1, min(10, mood_score))
            journal_text = request.form.get("journal", "").strip()
            habits       = request.form.getlist("habits")

            sentiment  = analyze_sentiment(journal_text)
            risk_level = calculate_risk_score(mood_score, sentiment)
            ai_message = generate_ai_response(
                context="wellness_check", tone=tone,
                mood=mood_score, journal=journal_text,
                habits=habits, risk=risk_level,
            )

            entry = {
                "mood":       mood_score,
                "journal":    journal_text,
                "habits":     habits,
                "sentiment":  sentiment,
                "risk":       risk_level,
                "ai_message": ai_message,
            }
            user_data[username]["entries"].append(entry)
            insight = {
                "mood":      mood_score,
                "sentiment": sentiment,
                "risk":      risk_level,
                "habits":    habits,
                "ai_message": ai_message,
            }

    last_entry   = user_data[username]["entries"][-1] if user_data[username]["entries"] else None
    appointments = _get_user_sessions(username)

    return render_template(
        "index.html", page="dashboard", active_tab="checkin",
        username=username, tone=tone,
        insight=insight, last_entry=last_entry,
        appointments=appointments,
    )


# ─────────────────────────────────────────────
# ROUTE: AI Chat Tab (page view)
# ─────────────────────────────────────────────
@app.route("/chat-page", methods=["GET", "POST"])
def chat_page():
    if "username" not in session:
        return redirect(url_for("index"))

    username = session["username"]
    tone     = session.get("tone", "motivational")
    ensure_user(username)

    if request.method == "POST":
        action = request.form.get("action")
        if action == "set_tone":
            tone           = request.form.get("tone", "motivational")
            session["tone"] = tone

    # Pass full history (capped at last 40 turns for display)
    chat_history  = user_data[username]["chat_history"][-40:]
    last_entry    = user_data[username]["entries"][-1] if user_data[username]["entries"] else None
    appointments  = _get_user_sessions(username)
    # Last stored session summary (if any)
    last_summary  = user_data[username].get("last_session_summary", None)

    return render_template(
        "index.html", page="dashboard", active_tab="chat",
        username=username, tone=tone,
        chat_history=chat_history,
        last_entry=last_entry,
        appointments=appointments,
        last_summary=last_summary,
        insight=None,
    )


# ─────────────────────────────────────────────
# ROUTE: Book Appointment Tab (page view only)
# ─────────────────────────────────────────────
@app.route("/book", methods=["GET"])
def book():
    if "username" not in session:
        return redirect(url_for("index"))

    username = session["username"]
    tone     = session.get("tone", "motivational")
    ensure_user(username)

    last_entry   = user_data[username]["entries"][-1] if user_data[username]["entries"] else None
    appointments = _get_user_sessions(username)

    return render_template(
        "index.html", page="dashboard", active_tab="book",
        username=username, tone=tone,
        appointments=appointments,
        last_entry=last_entry,
        insight=None,
        session_type_labels=SESSION_TYPE_LABELS,
    )


# ─────────────────────────────────────────────
# AJAX ROUTE: Fetch Live Availability Slots
# ─────────────────────────────────────────────
@app.route("/fetch-slots", methods=["POST"])
def fetch_slots():
    """
    AJAX endpoint — returns real-time availability slots.

    Request JSON:
      {
        supporter_id:  "t1",
        date:          "2025-01-15",
        session_type:  "solo_therapy",
        tz_offset:     60   ← user's UTC offset in minutes
      }

    Response JSON:
      {
        source:  "google" | "calendly" | "static",
        source_label: "🟢 Live — Google Calendar",
        slots:   [ { start_utc, end_utc, display_local, display_end, available } ],
        error:   null | "message",
        note:    null | "info string"
      }
    """
    if "username" not in session:
        return jsonify({"error": "Not authenticated"}), 401

    data         = request.get_json(silent=True) or {}
    supporter_id = data.get("supporter_id", "").strip()
    date_str     = data.get("date", "").strip()
    session_type = data.get("session_type", "solo_therapy").strip()
    try:
        tz_offset = int(data.get("tz_offset", 0))
    except (ValueError, TypeError):
        tz_offset = 0

    if not supporter_id or not date_str:
        return jsonify({"error": "supporter_id and date are required"}), 400

    logger.info(
        f"[/fetch-slots] user={session['username']} supporter={supporter_id} "
        f"date={date_str} type={session_type} tz={tz_offset:+d}min"
    )

    result = fetch_availability(
        supporter_id=supporter_id,
        date_str=date_str,
        session_type=session_type,
        tz_offset=tz_offset,
    )

    result["source_label"] = get_availability_source_label(result.get("source", ""))
    return jsonify(result)


# ─────────────────────────────────────────────
# AJAX ROUTE: Create Booking (confirm appointment)
# ─────────────────────────────────────────────
@app.route("/create-booking", methods=["POST"])
def create_booking_route():
    """
    AJAX endpoint — confirms a booking:
      1. Creates Google Calendar event (or Calendly booking)
      2. Stores session metadata
      3. Sends confirmation notification

    Request JSON:
      {
        supporter_id:  "t1",
        start_utc:     "2025-01-15T09:00:00+00:00",
        end_utc:       "2025-01-15T09:50:00+00:00",
        session_type:  "solo_therapy",
        format_type:   "video",
        notes:         "Feeling anxious about exams...",
        user_email:    "student@college.edu"   ← for calendar invite
      }

    Response JSON:
      {
        success:     true,
        booking_id:  "ms-1234567890-t1",
        event_link:  "https://calendar.google.com/...",
        source:      "google",
        error:       null
      }
    """
    if "username" not in session:
        return jsonify({"error": "Not authenticated"}), 401

    username = session["username"]
    data     = request.get_json(silent=True) or {}

    supporter_id = data.get("supporter_id", "").strip()
    start_utc    = data.get("start_utc", "").strip()
    end_utc      = data.get("end_utc", "").strip()
    session_type = data.get("session_type", "solo_therapy").strip()
    format_type  = data.get("format_type", "video").strip()
    notes        = data.get("notes", "").strip()
    user_email   = data.get("user_email", f"{username}@student.college.edu").strip()

    if not all([supporter_id, start_utc, end_utc]):
        return jsonify({"error": "supporter_id, start_utc, and end_utc are required"}), 400

    logger.info(
        f"[/create-booking] user={username} supporter={supporter_id} "
        f"type={session_type} format={format_type}"
    )

    result = create_booking(
        supporter_id=supporter_id,
        user_id=username,
        user_name=username.title(),
        user_email=user_email,
        start_utc=start_utc,
        end_utc=end_utc,
        session_type=session_type,
        format_type=format_type,
        notes=notes,
    )

    # Also store a lightweight record in user_data for the UI
    if result["success"]:
        supporter    = SUPPORTERS.get(supporter_id, {})
        session_type_lbl = SESSION_TYPE_LABELS.get(session_type, session_type)

        try:
            dt = datetime.fromisoformat(start_utc.replace("Z", "+00:00"))
            date_formatted = dt.strftime("%A, %d %B %Y")
            slot_formatted = dt.strftime("%H:%M")
        except Exception:
            date_formatted = start_utc[:10]
            slot_formatted = start_utc[11:16]

        appt = {
            "id":             result["booking_id"],
            "supporter_id":   supporter_id,
            "avatar":         supporter.get("avatar", "👤"),
            "name":           supporter.get("name", "Unknown"),
            "role":           supporter.get("role", "Supporter"),
            "date":           start_utc[:10],
            "date_formatted": date_formatted,
            "slot":           slot_formatted,
            "end_utc":        end_utc,
            "format":         FORMAT_LABELS.get(format_type, format_type),
            "session_type":   session_type_lbl,
            "notes":          notes,
            "event_link":     result.get("event_link"),
            "source":         result.get("source"),
            "status":         "confirmed",
        }
        user_data[username]["appointments"].append(appt)

    return jsonify(result)


# ─────────────────────────────────────────────
# AJAX ROUTE: Cancel a Booking
# ─────────────────────────────────────────────
@app.route("/cancel-booking", methods=["POST"])
def cancel_booking_route():
    """
    AJAX endpoint — cancels a session:
      - Removes Google Calendar event
      - Updates metadata store status to 'cancelled'
      - Removes from user's UI appointments list

    Request JSON:  { booking_id: "ms-1234567890-t1" }
    Response JSON: { success: true, error: null }
    """
    if "username" not in session:
        return jsonify({"error": "Not authenticated"}), 401

    username   = session["username"]
    data       = request.get_json(silent=True) or {}
    booking_id = data.get("booking_id", "").strip()

    if not booking_id:
        return jsonify({"error": "booking_id is required"}), 400

    # Cancel in metadata store (and optionally Google Calendar)
    session_meta = get_session(booking_id)
    if session_meta:
        gcal_event_id = session_meta.get("gcal_event_id")
        sid           = session_meta.get("supporter_id", "")
        if gcal_event_id and sid:
            cancel_google_event(sid, gcal_event_id)

    cancel_session(booking_id)

    # Remove from user's in-memory list
    ensure_user(username)
    user_data[username]["appointments"] = [
        a for a in user_data[username]["appointments"]
        if a.get("id") != booking_id
    ]

    logger.info(f"[/cancel-booking] Cancelled {booking_id} for {username}")
    return jsonify({"success": True, "error": None})


# ─────────────────────────────────────────────
# Legacy form-based cancel (kept for backward compat)
# ─────────────────────────────────────────────
@app.route("/cancel-appointment", methods=["POST"])
def cancel_appointment():
    if "username" not in session:
        return redirect(url_for("index"))

    username  = session["username"]
    ensure_user(username)
    appt_id   = request.form.get("appt_id", "")

    user_data[username]["appointments"] = [
        a for a in user_data[username]["appointments"]
        if str(a.get("id")) != str(appt_id)
    ]
    cancel_session(appt_id)
    return redirect(url_for("book"))


# ─────────────────────────────────────────────
# WEBHOOK: Calendly v2
# ─────────────────────────────────────────────
@app.route("/webhook/calendly", methods=["POST"])
def webhook_calendly():
    """
    Receives Calendly webhook events (invitee.created, invitee.canceled).

    Calendly signs requests with HMAC-SHA256.
    Set CALENDLY_WEBHOOK_SIGNING_KEY env var to enable validation.
    """
    raw_body  = request.get_data()
    signature = request.headers.get("Calendly-Webhook-Signature", "")
    payload   = request.get_json(silent=True) or {}

    result = process_calendly_webhook(payload, signature, raw_body)

    if not result["handled"] and result.get("error") == "Invalid signature":
        return jsonify({"error": "Invalid signature"}), 403

    logger.info(f"[Webhook/Calendly] {result}")
    return jsonify({"received": True, "result": result}), 200


# ─────────────────────────────────────────────
# WEBHOOK: Google Calendar Push Notifications
# ─────────────────────────────────────────────
@app.route("/webhook/google", methods=["POST"])
def webhook_google():
    """
    Receives Google Calendar push notification channel updates.
    Google sends a lightweight ping when a calendar changes.
    We respond with 200 OK and re-fetch availability on next request.
    """
    result = process_google_webhook(dict(request.headers), request.get_json(silent=True) or {})
    logger.info(f"[Webhook/Google] {result}")
    return "", 200   # Google requires 200 with no body


# ─────────────────────────────────────────────
# ROUTE: Register Google Push Channel (admin)
# ─────────────────────────────────────────────
@app.route("/admin/register-push/<supporter_id>")
def register_push(supporter_id):
    """
    Admin endpoint — register a Google Calendar push notification channel
    for a specific supporter. Call this once after deploying.

    Usage: GET /admin/register-push/t1
    """
    if "username" not in session:
        return redirect(url_for("index"))

    webhook_url = request.host_url.rstrip("/") + "/webhook/google"
    result      = register_google_push_channel(supporter_id, webhook_url)
    return jsonify(result)


# ─────────────────────────────────────────────
# ROUTE: Google OAuth2 Web Flow (optional)
# ─────────────────────────────────────────────
@app.route("/gcal-auth")
def gcal_auth():
    """Redirect the user to Google's OAuth2 consent page."""
    state    = session.get("username", "anonymous")
    auth_url = get_google_auth_url(state=state)
    if not auth_url:
        return render_template("index.html", page="login",
                               error="Google Calendar integration is not configured.")
    return redirect(auth_url)


@app.route("/gcal-callback")
def gcal_callback():
    """Handle Google OAuth2 callback — exchange code for tokens."""
    code  = request.args.get("code", "")
    error = request.args.get("error", "")

    if error:
        return render_template("index.html", page="login", active_tab="checkin",
                               error=f"Google auth failed: {error}")

    if not code:
        return render_template("index.html", page="login", active_tab="checkin",
                               error="No authorisation code received from Google.")

    result = exchange_google_code(code)
    if result["success"]:
        session["gcal_tokens"] = result["tokens"]
        logger.info("[GCal OAuth] Tokens stored in session")
        return redirect(url_for("dashboard"))
    else:
        return render_template("index.html", page="login", active_tab="checkin",
                               error=f"Token exchange failed: {result['error']}")


# ─────────────────────────────────────────────
# ROUTE: /chat — Fallback non-streaming AJAX
# Used as fallback if browser doesn't support SSE,
# or for programmatic access. Passes full history.
# ─────────────────────────────────────────────
@app.route("/chat", methods=["POST"])
def chat():
    if "username" not in session:
        return jsonify({"error": "Not authenticated"}), 401

    username = session["username"]
    tone     = session.get("tone", "motivational")
    ensure_user(username)

    data         = request.get_json(silent=True) or {}
    user_message = data.get("message", "").strip()

    if not user_message:
        return jsonify({"error": "Empty message"}), 400

    # Pass full conversation history so Maya has full context
    history  = user_data[username]["chat_history"]

    ai_reply = generate_ai_response(
        context="chat", tone=tone,
        mood=None, journal=None, habits=None, risk=None,
        user_message=user_message,
        history=history,
    )

    # Store the new turn in history
    user_data[username]["chat_history"].append({"user": user_message, "ai": ai_reply})
    logger.info(f"[/chat] user={username} history_len={len(user_data[username]['chat_history'])}")
    return jsonify({"reply": ai_reply})


# ─────────────────────────────────────────────
# ROUTE: /chat/stream — SSE Streaming (primary)
# Streams Maya's response token-by-token using
# Server-Sent Events (text/event-stream).
#
# Frontend sends POST with JSON { "message": "..." }
# Response is a stream of:
#   data: <token>\n\n
#   data: [DONE]\n\n
# ─────────────────────────────────────────────
@app.route("/chat/stream", methods=["POST"])
def chat_stream():
    if "username" not in session:
        return jsonify({"error": "Not authenticated"}), 401

    username = session["username"]
    ensure_user(username)

    data         = request.get_json(silent=True) or {}
    user_message = data.get("message", "").strip()

    if not user_message:
        return jsonify({"error": "Empty message"}), 400

    # Snapshot history BEFORE this turn (passed to Gemini for context)
    history = list(user_data[username]["chat_history"])

    # We'll accumulate the full streamed reply to save it after streaming
    # Use a mutable container accessible inside the generator closure
    accumulated = {"text": ""}

    def generate():
        for chunk in stream_maya_response(history, user_message):
            # chunk format: "data: <token>\n\n" or "data: [DONE]\n\n"
            if chunk.startswith("data: ") and chunk.strip() != "data: [DONE]":
                token = chunk[6:].rstrip("\n").replace("\\n", "\n")
                accumulated["text"] += token
            yield chunk

        # After stream ends, persist the completed turn into history
        full_reply = accumulated["text"].strip()
        if full_reply and full_reply not in ("", "[DONE]"):
            user_data[username]["chat_history"].append({
                "user": user_message,
                "ai":   full_reply,
            })
            logger.info(
                f"[/chat/stream] user={username} "
                f"history_len={len(user_data[username]['chat_history'])} "
                f"reply_len={len(full_reply)}"
            )

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":               "no-cache",
            "X-Accel-Buffering":           "no",   # disable Nginx buffering
            "Access-Control-Allow-Origin": "*",
        },
    )


# ─────────────────────────────────────────────
# ROUTE: /chat/summarise — End-of-session summary
# Call this when user ends a chat session.
# Gemini analyses full history and returns themes.
# ─────────────────────────────────────────────
@app.route("/chat/summarise", methods=["POST"])
def chat_summarise():
    if "username" not in session:
        return jsonify({"error": "Not authenticated"}), 401

    username = session["username"]
    ensure_user(username)

    history = user_data[username]["chat_history"]
    if len(history) < 2:
        return jsonify({
            "themes":      [],
            "summary":     "Session too short to summarise.",
            "mood_signal": "neutral",
        })

    summary = summarise_session(history)

    # Persist summary so it shows on next page load
    user_data[username]["last_session_summary"] = summary
    logger.info(f"[/chat/summarise] user={username} themes={summary.get('themes')}")
    return jsonify(summary)


# ─────────────────────────────────────────────
# ROUTE: /chat/clear — Clear session history
# Lets user start a fresh conversation with Maya
# ─────────────────────────────────────────────
@app.route("/chat/clear", methods=["POST"])
def chat_clear():
    if "username" not in session:
        return jsonify({"error": "Not authenticated"}), 401

    username = session["username"]
    ensure_user(username)

    # Summarise before clearing if there's meaningful history
    history = user_data[username]["chat_history"]
    if len(history) >= 3:
        summary = summarise_session(history)
        user_data[username]["last_session_summary"] = summary

    user_data[username]["chat_history"] = []
    logger.info(f"[/chat/clear] Cleared history for {username}")
    return jsonify({"success": True, "message": "Conversation cleared. Ready for a fresh start. 💙"})


# ─────────────────────────────────────────────
# ROUTE: /test-calendar — Google Calendar Diagnostic
# ─────────────────────────────────────────────
@app.route("/test-calendar")
def test_calendar():
    """
    Browser-friendly diagnostic page.
    Visit http://localhost:5000/test-calendar to verify the
    Google Calendar connection, credentials, and token status.

    Returns a clean HTML page with a full structured report.
    No login required so you can test before authenticating.
    """
    report = test_calendar_connection()

    # ── Render as a clean HTML diagnostic page ──
    overall      = report["overall"]
    creds        = report["credentials_file"]
    token        = report["token_file"]
    api          = report["api_connection"]
    supporters   = report["supporter_calendars"]
    freebusy     = report["freebusy_test"]
    instructions = report["setup_instructions"]

    color = {
        "✅": "#22c55e",
        "⚠": "#f59e0b",
        "❌": "#ef4444",
    }.get(overall[0], "#94a3b8")

    def badge(ok: bool, yes="✅", no="❌") -> str:
        return yes if ok else no

    rows = ""
    for sid, info in supporters.items():
        env  = info["env_var"]
        cid  = info["calendar_id"]
        icon = "✅" if info["configured"] else "❌ Not set"
        rows += (
            f"<tr><td>{info['name']}</td>"
            f"<td><code>{env}</code></td>"
            f"<td><code>{cid}</code></td>"
            f"<td>{icon}</td></tr>"
        )

    cal_names = ""
    if api.get("calendar_names"):
        for c in api["calendar_names"]:
            cal_names += f"<li><code>{c['id']}</code> — {c['summary']}</li>"
        cal_names = f"<ul style='margin-top:8px'>{cal_names}</ul>"

    instr_html = "".join(
        f"<li style='margin:6px 0'>{i}</li>" for i in instructions
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>MindfulSpace — Calendar Diagnostic</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: 'Segoe UI', sans-serif; background: #0f172a;
            color: #f1f5f9; padding: 40px 20px; line-height: 1.65; }}
    .container {{ max-width: 860px; margin: 0 auto; }}
    h1 {{ font-size: 1.8rem; margin-bottom: 4px; }}
    .subtitle {{ color: #94a3b8; margin-bottom: 32px; font-size: 0.95rem; }}
    .overall {{ font-size: 1.3rem; font-weight: 700; padding: 16px 24px;
                background: rgba(255,255,255,0.06); border-left: 4px solid {color};
                border-radius: 12px; margin-bottom: 32px; color: {color}; }}
    .card {{ background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1);
             border-radius: 16px; padding: 24px; margin-bottom: 20px; }}
    .card h2 {{ font-size: 1rem; color: #c4b5fd; margin-bottom: 16px;
                text-transform: uppercase; letter-spacing: 0.08em; font-weight: 600; }}
    .row {{ display: flex; justify-content: space-between; align-items: flex-start;
            padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.06); font-size: 0.92rem; }}
    .row:last-child {{ border-bottom: none; }}
    .label {{ color: #94a3b8; min-width: 180px; }}
    .value {{ color: #f1f5f9; word-break: break-all; }}
    code {{ background: rgba(255,255,255,0.08); padding: 2px 7px;
            border-radius: 5px; font-size: 0.85rem; color: #7dd3fc; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
    th {{ text-align: left; color: #94a3b8; font-weight: 500; padding: 8px 0;
          border-bottom: 1px solid rgba(255,255,255,0.1); }}
    td {{ padding: 9px 0; border-bottom: 1px solid rgba(255,255,255,0.05); vertical-align: top; }}
    td:not(:last-child) {{ padding-right: 16px; }}
    .setup {{ background: rgba(251, 191, 36, 0.08); border: 1px solid rgba(251,191,36,0.25);
              border-radius: 12px; padding: 20px 24px; }}
    .setup h2 {{ color: #fbbf24; margin-bottom: 12px; }}
    .setup ol {{ padding-left: 20px; }}
    .setup li {{ margin: 6px 0; font-size: 0.92rem; }}
    .btn {{ display: inline-block; padding: 10px 20px; border-radius: 10px;
            background: #6b5b95; color: white; text-decoration: none;
            font-weight: 600; font-size: 0.9rem; margin-top: 12px;
            transition: background 0.2s; }}
    .btn:hover {{ background: #7c6fa8; }}
    .btn-teal {{ background: #14b8a6; }}
    .btn-teal:hover {{ background: #0d9488; }}
    .actions {{ margin-top: 8px; display: flex; gap: 12px; flex-wrap: wrap; }}
    .err {{ color: #f87171; font-size: 0.88rem; margin-top: 4px; }}
  </style>
</head>
<body>
<div class="container">
  <h1>🌿 MindfulSpace — Calendar Diagnostic</h1>
  <p class="subtitle">Run at: {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</p>

  <div class="overall">Overall Status: {overall}</div>

  <!-- credentials.json -->
  <div class="card">
    <h2>① credentials.json</h2>
    <div class="row">
      <span class="label">File path</span>
      <span class="value"><code>{creds['path']}</code></span>
    </div>
    <div class="row">
      <span class="label">Exists</span>
      <span class="value">{badge(creds['exists'])}</span>
    </div>
    <div class="row">
      <span class="label">Valid JSON + structure</span>
      <span class="value">{badge(creds['valid'])}</span>
    </div>
    {'<div class="row"><span class="label">Error</span><span class="value err">' + creds["error"] + '</span></div>' if creds.get("error") else ""}
  </div>

  <!-- token.json -->
  <div class="card">
    <h2>② token.json (OAuth2 access token)</h2>
    <div class="row">
      <span class="label">File path</span>
      <span class="value"><code>{token['path']}</code></span>
    </div>
    <div class="row">
      <span class="label">Exists</span>
      <span class="value">{badge(token['exists'])}</span>
    </div>
    <div class="row">
      <span class="label">Valid structure</span>
      <span class="value">{badge(token['valid'])}</span>
    </div>
    {'<div class="row"><span class="label">Error</span><span class="value err">' + token["error"] + '</span></div>' if token.get("error") else ""}
    <div class="actions">
      <a href="/gcal-auth" class="btn">🔐 Authorise with Google (generates token.json)</a>
    </div>
  </div>

  <!-- API Connection -->
  <div class="card">
    <h2>③ Google Calendar API Connection</h2>
    <div class="row">
      <span class="label">API connected</span>
      <span class="value">{badge(api['success'])}</span>
    </div>
    <div class="row">
      <span class="label">Calendars accessible</span>
      <span class="value">{api.get('calendars_found', 0)}</span>
    </div>
    {'<div class="row"><span class="label">Error</span><span class="value err">' + api["error"] + '</span></div>' if api.get("error") else ""}
    {('<div class="row"><span class="label">Your calendars</span><span class="value">' + cal_names + '</span></div>') if cal_names else ""}
  </div>

  <!-- Supporter Calendars -->
  <div class="card">
    <h2>④ Supporter Calendar IDs</h2>
    <p style="color:#94a3b8;font-size:0.88rem;margin-bottom:16px">
      Set these as environment variables so each therapist's real calendar is used.
    </p>
    <table>
      <thead>
        <tr>
          <th>Name</th>
          <th>Env Variable</th>
          <th>Calendar ID</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </div>

  <!-- freebusy test -->
  <div class="card">
    <h2>⑤ Live freebusy Test</h2>
    <div class="row">
      <span class="label">Test passed</span>
      <span class="value">{badge(freebusy['success'])}</span>
    </div>
    <div class="row">
      <span class="label">Test date</span>
      <span class="value">{freebusy.get('test_date', 'N/A')}</span>
    </div>
    <div class="row">
      <span class="label">Supporter tested</span>
      <span class="value">{freebusy.get('supporter', 'N/A')}</span>
    </div>
    <div class="row">
      <span class="label">Slots returned</span>
      <span class="value">{freebusy.get('slots_found', 0)}</span>
    </div>
    {'<div class="row"><span class="label">Error</span><span class="value err">' + freebusy["error"] + '</span></div>' if freebusy.get("error") else ""}
  </div>

  <!-- Setup Instructions -->
  {('<div class="setup"><h2>📋 Setup Steps Needed</h2><ol>' + instr_html + '</ol></div>') if instructions else '<div class="card" style="border-color:rgba(34,197,94,0.3)"><h2 style="color:#22c55e">✅ All steps complete — calendar is fully connected!</h2></div>'}

  <div class="actions" style="margin-top:24px">
    <a href="/" class="btn btn-teal">← Back to App</a>
    <a href="/test-calendar" class="btn" style="background:#334155">🔄 Refresh Diagnostic</a>
  </div>
</div>
</body>
</html>"""

    return html, 200, {"Content-Type": "text/html"}


# ─────────────────────────────────────────────
# AGENTIC DISTRESS DETECTION — In-Memory Log
# Anonymised flagged session records for therapist review.
# Structure: [ { session_id, timestamp, level, trigger,
#                keywords, sentiment, username_hash } ]
# ─────────────────────────────────────────────
import hashlib

FLAGGED_SESSIONS: list = []   # anonymised distress log

def _hash_user(username: str) -> str:
    """One-way hash — therapist sees pattern, not identity."""
    return hashlib.sha256(username.encode()).hexdigest()[:12]


# ─────────────────────────────────────────────
# ROUTE: /chat/detect — Run Distress Detection
# Called by the frontend after EVERY AI response.
# Analyses the user's last 3–5 messages.
# Returns detection result JSON so the UI can decide
# whether to surface the intervention modal.
# ─────────────────────────────────────────────
@app.route("/chat/detect", methods=["POST"])
def chat_detect():
    """
    Lightweight agentic endpoint — runs after each chat turn.

    Request JSON:
      { "messages": ["last msg", "second last", ...] }   ← user-only messages
      (frontend sends last 5 user messages, newest last)

    Response JSON:
      {
        level:          "none" | "moderate" | "crisis",
        trigger:        "keyword_crisis" | ... | null,
        should_intervene: bool,
        message:        str | null,
        icall_number:   str | null,
        keywords_found: list[str],
        sentiment_score: float,
      }
    """
    if "username" not in session:
        return jsonify({"error": "Not authenticated"}), 401

    username = session["username"]
    ensure_user(username)

    data     = request.get_json(silent=True) or {}
    messages = data.get("messages", [])

    if not messages:
        return jsonify({"level": "none", "should_intervene": False})

    # ── Retrieve consecutive low count from user session state ──
    consecutive = user_data[username].get("consecutive_low_count", 0)

    # ── Run detection ──
    result = run_distress_detection(
        recent_messages=messages,
        consecutive_low_count=consecutive,
    )

    # ── Persist updated consecutive count ──
    user_data[username]["consecutive_low_count"] = result["consecutive_low"]

    # ── Log flagged sessions (anonymised) ──
    if result["should_intervene"]:
        flag_record = {
            "id":            f"flag-{int(time.time())}-{_hash_user(username)[:6]}",
            "timestamp":     datetime.now(tz=timezone.utc).isoformat(),
            "level":         result["level"],
            "trigger":       result["trigger"],
            "keywords":      result["keywords_found"],
            "sentiment":     result["sentiment_score"],
            "user_hash":     _hash_user(username),   # anonymised
            "message_count": len(user_data[username]["chat_history"]),
        }
        FLAGGED_SESSIONS.append(flag_record)
        logger.warning(
            f"[Distress] level={result['level']} trigger={result['trigger']} "
            f"user_hash={flag_record['user_hash']} keywords={result['keywords_found']}"
        )

    return jsonify(result)


# ─────────────────────────────────────────────
# ROUTE: /flagged-sessions — Therapist Dashboard
# Shows anonymised distress signal log.
# In production: protect with therapist auth.
# ─────────────────────────────────────────────
@app.route("/flagged-sessions")
def flagged_sessions():
    """
    Therapist-facing dashboard — shows anonymised distress flags.
    All identifying info is hashed. Therapists see patterns, not names.

    In production: add role-based authentication before exposing this.
    For MVP: accessible at /flagged-sessions for demonstration.
    """
    flags = sorted(FLAGGED_SESSIONS, key=lambda x: x["timestamp"], reverse=True)

    total    = len(flags)
    crisis   = sum(1 for f in flags if f["level"] == "crisis")
    moderate = sum(1 for f in flags if f["level"] == "moderate")

    rows_html = ""
    for f in flags:
        level_color = {
            "crisis":   "#f87171",
            "moderate": "#fbbf24",
        }.get(f["level"], "#94a3b8")

        kw_badges = "".join(
            f"<span style='background:rgba(255,255,255,0.07);padding:2px 8px;"
            f"border-radius:20px;font-size:0.78rem;margin:2px;display:inline-block;'>"
            f"{kw}</span>"
            for kw in (f.get("keywords") or [])[:6]
        )

        rows_html += f"""
        <tr>
          <td style="color:#94a3b8;font-size:0.82rem;">{f['timestamp'][:19].replace('T',' ')}</td>
          <td><span style="color:{level_color};font-weight:600;text-transform:uppercase;
              font-size:0.8rem;">{f['level']}</span></td>
          <td style="font-size:0.82rem;color:#c4b5fd;">{f.get('trigger','—')}</td>
          <td style="font-size:0.82rem;">{kw_badges or '—'}</td>
          <td style="font-size:0.82rem;color:#94a3b8;">{f.get('sentiment',0):.2f}</td>
          <td><code style="font-size:0.78rem;color:#7dd3fc;">{f['user_hash']}</code></td>
          <td style="font-size:0.82rem;color:#94a3b8;">{f.get('message_count',0)} msgs</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>MindfulSpace — Therapist Distress Dashboard</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:'Segoe UI',sans-serif;background:#0d1117;color:#f1f5f9;
         padding:40px 20px;line-height:1.6}}
    .wrap{{max-width:1100px;margin:0 auto}}
    h1{{font-size:1.6rem;margin-bottom:4px}}
    .sub{{color:#94a3b8;font-size:0.88rem;margin-bottom:32px}}
    .stats{{display:flex;gap:16px;margin-bottom:32px;flex-wrap:wrap}}
    .stat{{background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);
           border-radius:14px;padding:20px 28px;flex:1;min-width:160px}}
    .stat-n{{font-size:2rem;font-weight:700;margin-bottom:2px}}
    .stat-l{{font-size:0.82rem;color:#94a3b8}}
    .card{{background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);
           border-radius:16px;overflow:hidden;margin-bottom:24px}}
    .card-head{{padding:16px 24px;border-bottom:1px solid rgba(255,255,255,0.07);
                font-size:0.85rem;font-weight:600;color:#c4b5fd;text-transform:uppercase;
                letter-spacing:0.06em}}
    table{{width:100%;border-collapse:collapse}}
    th{{text-align:left;color:#64748b;font-weight:500;font-size:0.8rem;
        padding:10px 16px;border-bottom:1px solid rgba(255,255,255,0.06)}}
    td{{padding:12px 16px;border-bottom:1px solid rgba(255,255,255,0.04);vertical-align:top}}
    tr:last-child td{{border-bottom:none}}
    tr:hover td{{background:rgba(255,255,255,0.02)}}
    .empty{{padding:40px;text-align:center;color:#64748b;font-size:0.9rem}}
    .warn{{background:rgba(251,191,36,0.07);border:1px solid rgba(251,191,36,0.2);
           border-radius:12px;padding:16px 20px;margin-bottom:24px;font-size:0.85rem;
           color:#fde68a;line-height:1.65}}
    .btn{{display:inline-block;padding:9px 18px;border-radius:10px;background:#6b5b95;
          color:white;text-decoration:none;font-weight:600;font-size:0.85rem;margin-top:4px}}
    .btn:hover{{background:#7c6fa8}}
    .btn-red{{background:rgba(239,68,68,0.15);border:1px solid rgba(239,68,68,0.3);color:#f87171}}
    .btn-red:hover{{background:rgba(239,68,68,0.25)}}
  </style>
</head>
<body>
<div class="wrap">
  <h1>🧠 Therapist Distress Dashboard</h1>
  <p class="sub">Anonymised distress signal log · All user identifiers are hashed · Auto-updated each session</p>

  <div class="warn">
    ⚠️ <strong>Privacy Notice:</strong> This dashboard contains anonymised data only.
    User identities are protected by one-way SHA-256 hashing. In production, this route
    must be protected by therapist-level role authentication before deployment.
  </div>

  <div class="stats">
    <div class="stat">
      <div class="stat-n">{total}</div>
      <div class="stat-l">Total Flags</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="color:#f87171">{crisis}</div>
      <div class="stat-l">Crisis Flags</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="color:#fbbf24">{moderate}</div>
      <div class="stat-l">Moderate Flags</div>
    </div>
    <div class="stat">
      <div class="stat-n" style="color:#34d399">{len(set(f['user_hash'] for f in flags))}</div>
      <div class="stat-l">Unique Users</div>
    </div>
  </div>

  <div class="card">
    <div class="card-head">🚨 Distress Signal Log (newest first)</div>
    {"<table><thead><tr><th>Timestamp (UTC)</th><th>Level</th><th>Trigger</th><th>Keywords Detected</th><th>Sentiment</th><th>User Hash</th><th>Session Depth</th></tr></thead><tbody>" + rows_html + "</tbody></table>" if flags else '<div class="empty">✅ No distress flags recorded yet. This is updated in real time as users chat with Maya.</div>'}
  </div>

  <div style="display:flex;gap:12px;flex-wrap:wrap;">
    <a href="/" class="btn">← Back to App</a>
    <a href="/flagged-sessions" class="btn" style="background:#1e2d4a;">🔄 Refresh</a>
  </div>
</div>
</body>
</html>"""

    return html, 200, {"Content-Type": "text/html"}


# ─────────────────────────────────────────────
# ROUTE: Logout
# ─────────────────────────────────────────────
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


# ─────────────────────────────────────────────
# INTERNAL HELPERS
# ─────────────────────────────────────────────
def _get_user_sessions(username: str) -> list:
    """
    Merge in-memory appointments list with SESSION_STORE records
    for a complete view of all user bookings.
    """
    ensure_user(username)
    return user_data[username]["appointments"]


# ─────────────────────────────────────────────
# APScheduler — 24h Reminder Jobs
# ─────────────────────────────────────────────
def _start_scheduler():
    """
    Start background job scheduler for sending 24h reminder notifications.
    Checks every hour for sessions starting within the next 24–25 hours.
    """
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from datetime import timedelta

        def check_and_send_reminders():
            now       = datetime.now(tz=timezone.utc)
            window_lo = now + timedelta(hours=24)
            window_hi = now + timedelta(hours=25)

            for booking_id, meta in SESSION_STORE.items():
                if meta.get("status") != "confirmed":
                    continue
                try:
                    start = datetime.fromisoformat(
                        meta["start_utc"].replace("Z", "+00:00")
                    )
                    if window_lo <= start <= window_hi:
                        send_reminder_notification(booking_id)
                except Exception:
                    pass

        scheduler = BackgroundScheduler()
        scheduler.add_job(check_and_send_reminders, "interval", hours=1, id="reminders")
        scheduler.start()
        logger.info("[Scheduler] APScheduler started — checking reminders every hour")

    except ImportError:
        logger.warning("[Scheduler] APScheduler not installed — reminder jobs disabled")
    except Exception as e:
        logger.error(f"[Scheduler] Failed to start: {e}")


# ─────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────
if __name__ == "__main__":
    _start_scheduler()
    app.run(debug=True, port=5000)

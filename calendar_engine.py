"""
calendar_engine.py — Stub module for Google Calendar integration

Provides in-memory session storage and stub implementations for all
calendar-related functions. Replace with real Google Calendar API
integration when ready.
"""

SESSION_STORE = {}


def fetch_availability(supporter_id=None, date_str=None, session_type="solo_therapy", tz_offset=0):
    """Return available time slots for a supporter on a given date."""
    return {
        "slots": [],
        "source": "stub",
        "source_label": "Unavailable (Calendar not configured)",
        "error": None,
        "note": "Google Calendar integration not configured. Set up credentials.json to enable live slots.",
    }


def create_booking(supporter_id=None, user_id=None, user_name=None, user_email=None,
                   start_utc=None, end_utc=None, session_type="solo_therapy",
                   format_type="video", notes=""):
    """Create a booking and return result with success flag."""
    booking_id = f"ms-{int(__import__('time').time())}-{supporter_id}"
    SESSION_STORE[booking_id] = {
        "supporter_id": supporter_id,
        "user_id": user_id,
        "user_name": user_name,
        "user_email": user_email,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "session_type": session_type,
        "format_type": format_type,
        "notes": notes,
        "status": "confirmed",
    }
    return {"success": True, "booking_id": booking_id, "event_link": None, "source": "stub", "error": None}


def cancel_session(booking_id):
    """Cancel a session by booking ID."""
    SESSION_STORE.pop(booking_id, None)
    return {"status": "cancelled"}


def get_session(booking_id):
    """Retrieve session metadata by booking ID."""
    return SESSION_STORE.get(booking_id)


def list_sessions_for_user(user_id):
    """List all sessions for a given user."""
    return [v for v in SESSION_STORE.values() if v.get("user_id") == user_id]


def cancel_google_event(supporter_id, event_id):
    """Cancel a Google Calendar event. Stub: no-op."""
    return {"status": "cancelled", "message": "Google Calendar not configured"}


def process_calendly_webhook(payload, signature, raw_body):
    """Process a Calendly webhook event."""
    return {"handled": True, "status": "ignored", "message": "Calendly not configured"}


def process_google_webhook(headers, payload):
    """Process a Google Calendar push notification."""
    return {"handled": True, "status": "ignored", "message": "Google Calendar not configured"}


def get_google_auth_url(state=None):
    """Generate Google OAuth2 authorization URL. Returns None when not configured."""
    return None


def exchange_google_code(code):
    """Exchange Google OAuth2 code for tokens."""
    return {"success": False, "error": "Google Calendar not configured"}


def register_google_push_channel(supporter_id, webhook_url):
    """Register a Google Calendar push notification channel."""
    return {"status": "error", "message": "Google Calendar not configured"}


def get_availability_source_label(source):
    """Return a human-readable label for the availability source."""
    labels = {
        "google": "Live — Google Calendar",
        "calendly": "Live — Calendly",
        "stub": "Unavailable (Calendar not configured)",
    }
    return labels.get(source, "Unavailable")


def test_calendar_connection():
    """Diagnostic: test Google Calendar API connection."""
    return {
        "overall": "❌ Google Calendar not configured",
        "credentials_file": {
            "path": "credentials.json",
            "exists": False,
            "valid": False,
            "error": "File not found. Follow instructions in credentials.json.example.",
        },
        "token_file": {
            "path": "token.json",
            "exists": False,
            "valid": False,
            "error": "File not found. Authorise via /gcal-auth after setting up credentials.json.",
        },
        "api_connection": {
            "success": False,
            "calendars_found": 0,
            "error": "Cannot connect — credentials.json missing.",
        },
        "supporter_calendars": {},
        "freebusy_test": {
            "success": False,
            "test_date": "N/A",
            "supporter": "N/A",
            "slots_found": 0,
            "error": "Skipped — API not connected.",
        },
        "setup_instructions": [
            "1. Follow the setup guide in credentials.json.example",
            "2. Place credentials.json in the project root",
            "3. Visit /gcal-auth to authorise with Google",
            "4. Set GOOGLE_CALENDAR_T1..P3 env vars to therapist calendar IDs",
            "5. Visit /test-calendar to verify the connection",
        ],
    }


def send_reminder_notification(booking_id):
    """Send a 24h reminder notification for a session. Stub: logs only."""
    meta = SESSION_STORE.get(booking_id)
    if meta:
        print(f"[Reminder] Session {booking_id} starts within 24h — user: {meta.get('user_id')}")
    return {"status": "sent", "message": "Reminder sent (stub)"}

from tz_helper import now_bz
"""Calendar manager — supports Google Calendar and Microsoft Outlook/Teams."""

import os
import json
import asyncio
from datetime import datetime, timedelta
from pathlib import Path

# Calendar provider: "google", "microsoft", or "both"
CALENDAR_PROVIDER = os.getenv("CALENDAR_PROVIDER", "google")

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

# ============================================================
# GOOGLE CALENDAR
# ============================================================

GOOGLE_CREDS_FILE = DATA_DIR / "google_credentials.json"
GOOGLE_TOKEN_FILE = DATA_DIR / "google_token.json"
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar"]


def google_authenticate():
    """One-time Google OAuth2 authentication."""
    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request

        creds = None
        if GOOGLE_TOKEN_FILE.exists():
            creds = Credentials.from_authorized_user_file(str(GOOGLE_TOKEN_FILE), GOOGLE_SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(str(GOOGLE_CREDS_FILE), GOOGLE_SCOPES)
                creds = flow.run_local_server(port=0)

            with open(GOOGLE_TOKEN_FILE, "w") as f:
                f.write(creds.to_json())

        return creds
    except Exception as e:
        print(f"Error autenticando Google: {e}")
        return None


def get_google_events(date_str=None, days=1):
    """Get events from Google Calendar."""
    try:
        from googleapiclient.discovery import build
        creds = google_authenticate()
        if not creds:
            return []

        service = build("calendar", "v3", credentials=creds)

        if date_str:
            start = datetime.strptime(date_str, "%Y-%m-%d")
        else:
            start = now_bz().replace(hour=0, minute=0, second=0, microsecond=0)

        end = start + timedelta(days=days)

        events_result = service.events().list(
            calendarId="primary",
            timeMin=start.isoformat() + "Z",
            timeMax=end.isoformat() + "Z",
            maxResults=20,
            singleEvents=True,
            orderBy="startTime"
        ).execute()

        events = []
        for event in events_result.get("items", []):
            start_dt = event["start"].get("dateTime", event["start"].get("date", ""))
            end_dt = event["end"].get("dateTime", event["end"].get("date", ""))

            # Parse time
            start_time = ""
            end_time = ""
            if "T" in start_dt:
                start_time = start_dt.split("T")[1][:5]
            if "T" in end_dt:
                end_time = end_dt.split("T")[1][:5]

            events.append({
                "title": event.get("summary", "Sin titulo"),
                "start_time": start_time,
                "end_time": end_time,
                "location": event.get("location", ""),
                "description": event.get("description", ""),
                "source": "google",
                "meeting_url": event.get("hangoutLink", ""),
            })
        return events
    except Exception as e:
        print(f"Error obteniendo eventos Google: {e}")
        return []


def create_google_event(title, start_dt, end_dt=None, location=None, description=None):
    """Create event in Google Calendar."""
    try:
        from googleapiclient.discovery import build
        creds = google_authenticate()
        if not creds:
            return None

        service = build("calendar", "v3", credentials=creds)

        if not end_dt:
            end_dt = (datetime.strptime(start_dt, "%Y-%m-%dT%H:%M") + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")

        event = {
            "summary": title,
            "start": {"dateTime": start_dt + ":00", "timeZone": "America/Belize"},
            "end": {"dateTime": end_dt + ":00", "timeZone": "America/Belize"},
        }
        if location:
            event["location"] = location
        if description:
            event["description"] = description

        result = service.events().insert(calendarId="primary", body=event).execute()
        return result.get("id")
    except Exception as e:
        print(f"Error creando evento Google: {e}")
        return None


# ============================================================
# MICROSOFT OUTLOOK / TEAMS
# ============================================================

MS_CLIENT_ID = os.getenv("MS_CLIENT_ID", "")
MS_CLIENT_SECRET = os.getenv("MS_CLIENT_SECRET", "")
MS_TENANT_ID = os.getenv("MS_TENANT_ID", "common")
MS_TOKEN_FILE = DATA_DIR / "ms_token.json"
MS_SCOPES = ["Calendars.ReadWrite", "User.Read"]


def ms_get_token():
    """Get Microsoft access token from stored refresh token."""
    import httpx

    if not MS_TOKEN_FILE.exists():
        return None

    with open(MS_TOKEN_FILE) as f:
        token_data = json.load(f)

    # Check if token is still valid
    if token_data.get("expires_at", 0) > now_bz().timestamp():
        return token_data["access_token"]

    # Refresh token
    refresh_token = token_data.get("refresh_token")
    if not refresh_token:
        return None

    resp = httpx.post(
        f"https://login.microsoftonline.com/{MS_TENANT_ID}/oauth2/v2.0/token",
        data={
            "client_id": MS_CLIENT_ID,
            "client_secret": MS_CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
            "scope": " ".join(MS_SCOPES),
        }
    )

    if resp.status_code == 200:
        new_data = resp.json()
        new_data["expires_at"] = now_bz().timestamp() + new_data.get("expires_in", 3600)
        with open(MS_TOKEN_FILE, "w") as f:
            json.dump(new_data, f)
        return new_data["access_token"]

    return None


def ms_authenticate_url():
    """Generate Microsoft OAuth2 authorization URL."""
    base = f"https://login.microsoftonline.com/{MS_TENANT_ID}/oauth2/v2.0/authorize"
    params = {
        "client_id": MS_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": "http://localhost:8400/callback",
        "scope": " ".join(MS_SCOPES),
        "response_mode": "query",
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{base}?{query}"


def ms_exchange_code(code):
    """Exchange authorization code for tokens."""
    import httpx

    resp = httpx.post(
        f"https://login.microsoftonline.com/{MS_TENANT_ID}/oauth2/v2.0/token",
        data={
            "client_id": MS_CLIENT_ID,
            "client_secret": MS_CLIENT_SECRET,
            "code": code,
            "redirect_uri": "http://localhost:8400/callback",
            "grant_type": "authorization_code",
            "scope": " ".join(MS_SCOPES),
        }
    )

    if resp.status_code == 200:
        token_data = resp.json()
        token_data["expires_at"] = now_bz().timestamp() + token_data.get("expires_in", 3600)
        with open(MS_TOKEN_FILE, "w") as f:
            json.dump(token_data, f)
        return True
    return False


def get_microsoft_events(date_str=None, days=1):
    """Get events from Microsoft Outlook/Teams calendar."""
    import httpx

    token = ms_get_token()
    if not token:
        return []

    if date_str:
        start = datetime.strptime(date_str, "%Y-%m-%d")
    else:
        start = now_bz().replace(hour=0, minute=0, second=0, microsecond=0)

    end = start + timedelta(days=days)

    try:
        resp = httpx.get(
            "https://graph.microsoft.com/v1.0/me/calendarView",
            params={
                "startDateTime": start.strftime("%Y-%m-%dT00:00:00"),
                "endDateTime": end.strftime("%Y-%m-%dT23:59:59"),
                "$orderby": "start/dateTime",
                "$top": 20,
            },
            headers={"Authorization": f"Bearer {token}"}
        )

        if resp.status_code != 200:
            return []

        events = []
        for event in resp.json().get("value", []):
            start_dt = event.get("start", {}).get("dateTime", "")
            end_dt = event.get("end", {}).get("dateTime", "")

            start_time = start_dt.split("T")[1][:5] if "T" in start_dt else ""
            end_time = end_dt.split("T")[1][:5] if "T" in end_dt else ""

            # Check for Teams meeting
            meeting_url = ""
            if event.get("isOnlineMeeting"):
                meeting_url = event.get("onlineMeeting", {}).get("joinUrl", "")

            events.append({
                "title": event.get("subject", "Sin titulo"),
                "start_time": start_time,
                "end_time": end_time,
                "location": event.get("location", {}).get("displayName", ""),
                "description": event.get("bodyPreview", ""),
                "source": "microsoft",
                "meeting_url": meeting_url,
            })
        return events
    except Exception as e:
        print(f"Error obteniendo eventos Microsoft: {e}")
        return []


def create_microsoft_event(title, start_dt, end_dt=None, location=None, description=None):
    """Create event in Microsoft calendar."""
    import httpx

    token = ms_get_token()
    if not token:
        return None

    if not end_dt:
        end_dt = (datetime.strptime(start_dt, "%Y-%m-%dT%H:%M") + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")

    event = {
        "subject": title,
        "start": {"dateTime": start_dt + ":00", "timeZone": "America/Belize"},
        "end": {"dateTime": end_dt + ":00", "timeZone": "America/Belize"},
    }
    if location:
        event["location"] = {"displayName": location}
    if description:
        event["body"] = {"contentType": "text", "content": description}

    try:
        resp = httpx.post(
            "https://graph.microsoft.com/v1.0/me/events",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=event
        )
        if resp.status_code in (200, 201):
            return resp.json().get("id")
    except Exception as e:
        print(f"Error creando evento Microsoft: {e}")
    return None


# ============================================================
# UNIFIED INTERFACE
# ============================================================

def get_all_events(date_str=None, days=1):
    """Get events from all configured calendar providers."""
    events = []
    provider = CALENDAR_PROVIDER.lower()

    if provider in ("google", "both"):
        events.extend(get_google_events(date_str, days))

    if provider in ("microsoft", "both"):
        events.extend(get_microsoft_events(date_str, days))

    # Sort by start time
    events.sort(key=lambda e: e.get("start_time", "99:99"))
    return events


def create_event(title, start_dt, end_dt=None, location=None, description=None):
    """Create event in the primary calendar provider."""
    provider = CALENDAR_PROVIDER.lower()

    if provider in ("google", "both"):
        return create_google_event(title, start_dt, end_dt, location, description)
    elif provider == "microsoft":
        return create_microsoft_event(title, start_dt, end_dt, location, description)
    return None


def format_events_text(events):
    """Format events list as readable text."""
    if not events:
        return "No tienes eventos programados."

    lines = []
    for e in events:
        time_range = ""
        if e["start_time"]:
            time_range = e["start_time"]
            if e["end_time"]:
                time_range += f"-{e['end_time']}"

        source_tag = ""
        if e["source"] == "microsoft":
            source_tag = " [Teams]" if e.get("meeting_url") else " [Outlook]"
        elif e["source"] == "google":
            source_tag = " [GCal]"

        location = f" ({e['location']})" if e.get("location") else ""
        lines.append(f"  {time_range} — {e['title']}{source_tag}{location}")

    return "\n".join(lines)

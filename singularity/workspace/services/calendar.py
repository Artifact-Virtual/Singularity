"""
Google Calendar service — events, create, update, delete.

Usage:
    cal = CalendarService(creds)
    events = cal.events()  # next 10 upcoming
    events = cal.events(days=7)  # next 7 days
    cal.create_event("Meeting", "2026-03-15T10:00:00", "2026-03-15T11:00:00")
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from googleapiclient.discovery import build

log = logging.getLogger("singularity.workspace.calendar")


class CalendarService:
    """Google Calendar API wrapper."""

    def __init__(self, creds):
        self._service = build("calendar", "v3", credentials=creds)

    def calendars(self) -> list[dict]:
        """List all calendars."""
        result = self._service.calendarList().list().execute()
        return [
            {
                "id": cal["id"],
                "summary": cal.get("summary", ""),
                "primary": cal.get("primary", False),
                "backgroundColor": cal.get("backgroundColor", ""),
            }
            for cal in result.get("items", [])
        ]

    def events(
        self,
        calendar_id: str = "primary",
        days: int = 7,
        max_results: int = 20,
        query: Optional[str] = None,
    ) -> list[dict]:
        """
        List upcoming events.
        
        Args:
            calendar_id: Calendar ID (default: primary).
            days: Number of days ahead to look.
            max_results: Maximum events to return.
            query: Free text search query.
        """
        now = datetime.now(timezone.utc)
        time_min = now.isoformat()
        time_max = (now + timedelta(days=days)).isoformat()

        kwargs = {
            "calendarId": calendar_id,
            "timeMin": time_min,
            "timeMax": time_max,
            "maxResults": max_results,
            "singleEvents": True,
            "orderBy": "startTime",
        }
        if query:
            kwargs["q"] = query

        result = self._service.events().list(**kwargs).execute()
        events = []
        for event in result.get("items", []):
            start = event.get("start", {})
            end = event.get("end", {})
            events.append({
                "id": event["id"],
                "summary": event.get("summary", "(No title)"),
                "start": start.get("dateTime", start.get("date", "")),
                "end": end.get("dateTime", end.get("date", "")),
                "location": event.get("location", ""),
                "description": event.get("description", ""),
                "status": event.get("status", ""),
                "attendees": [
                    a.get("email", "") for a in event.get("attendees", [])
                ],
                "link": event.get("htmlLink", ""),
            })
        return events

    def create_event(
        self,
        summary: str,
        start: str,
        end: str,
        calendar_id: str = "primary",
        description: Optional[str] = None,
        location: Optional[str] = None,
        attendees: Optional[list[str]] = None,
        timezone_: str = "America/New_York",
    ) -> dict:
        """
        Create a calendar event.
        
        Args:
            summary: Event title.
            start: Start time (ISO 8601 format).
            end: End time (ISO 8601 format).
            description: Event description.
            location: Event location.
            attendees: List of attendee emails.
            timezone_: Timezone for the event.
        """
        event = {
            "summary": summary,
            "start": {"dateTime": start, "timeZone": timezone_},
            "end": {"dateTime": end, "timeZone": timezone_},
        }
        if description:
            event["description"] = description
        if location:
            event["location"] = location
        if attendees:
            event["attendees"] = [{"email": e} for e in attendees]

        result = self._service.events().insert(
            calendarId=calendar_id, body=event
        ).execute()
        log.info(f"Event created: {summary} → {result['id']}")
        return {
            "id": result["id"],
            "summary": summary,
            "link": result.get("htmlLink", ""),
        }

    def delete_event(self, event_id: str, calendar_id: str = "primary") -> None:
        """Delete a calendar event."""
        self._service.events().delete(
            calendarId=calendar_id, eventId=event_id
        ).execute()
        log.info(f"Event deleted: {event_id}")

    def today(self, calendar_id: str = "primary") -> list[dict]:
        """Get today's events."""
        return self.events(calendar_id=calendar_id, days=1)

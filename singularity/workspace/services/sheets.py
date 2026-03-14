"""
Google Sheets service — create, read, write, append rows.

Usage:
    sheets = SheetsService(creds)
    data = sheets.read("spreadsheet_id", "Sheet1!A1:D10")
    sheets.write("spreadsheet_id", "Sheet1!A1", [["Name", "Value"], ["foo", "bar"]])
    sheets.append_rows("spreadsheet_id", "Sheet1", [["new", "row"]])
    sheet = sheets.create("My Spreadsheet")
"""
from __future__ import annotations

import logging
from typing import Optional

from googleapiclient.discovery import build

log = logging.getLogger("singularity.workspace.sheets")


class SheetsService:
    """Google Sheets API wrapper."""

    def __init__(self, creds):
        self._service = build("sheets", "v4", credentials=creds)
        self._drive = build("drive", "v3", credentials=creds)

    def create(self, title: str, sheet_names: Optional[list[str]] = None) -> dict:
        """
        Create a new spreadsheet.
        
        Args:
            title: Spreadsheet title.
            sheet_names: List of sheet/tab names to create.
        """
        body = {"properties": {"title": title}}
        if sheet_names:
            body["sheets"] = [
                {"properties": {"title": name}} for name in sheet_names
            ]

        result = self._service.spreadsheets().create(body=body).execute()
        sid = result["spreadsheetId"]
        log.info(f"Spreadsheet created: {title} → {sid}")
        return {
            "id": sid,
            "title": title,
            "url": f"https://docs.google.com/spreadsheets/d/{sid}/edit",
            "sheets": [s["properties"]["title"] for s in result.get("sheets", [])],
        }

    def read(self, spreadsheet_id: str, range_: str) -> list[list]:
        """
        Read values from a range.
        
        Args:
            spreadsheet_id: Spreadsheet ID.
            range_: A1 notation range (e.g., "Sheet1!A1:D10").
            
        Returns:
            2D list of cell values.
        """
        result = self._service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id, range=range_
        ).execute()
        return result.get("values", [])

    def write(self, spreadsheet_id: str, range_: str, values: list[list]) -> dict:
        """
        Write values to a range.
        
        Args:
            spreadsheet_id: Spreadsheet ID.
            range_: A1 notation range.
            values: 2D list of values to write.
        """
        result = self._service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=range_,
            valueInputOption="USER_ENTERED",
            body={"values": values},
        ).execute()
        log.info(f"Wrote {result.get('updatedCells', 0)} cells to {range_}")
        return result

    def append_rows(self, spreadsheet_id: str, sheet_name: str, rows: list[list]) -> dict:
        """
        Append rows to the end of a sheet.
        
        Args:
            spreadsheet_id: Spreadsheet ID.
            sheet_name: Sheet/tab name.
            rows: List of rows (each row is a list of values).
        """
        result = self._service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_name}!A1",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": rows},
        ).execute()
        log.info(f"Appended {len(rows)} rows to {sheet_name}")
        return result

    def get_metadata(self, spreadsheet_id: str) -> dict:
        """Get spreadsheet metadata (title, sheets, etc.)."""
        result = self._service.spreadsheets().get(
            spreadsheetId=spreadsheet_id
        ).execute()
        return {
            "id": result["spreadsheetId"],
            "title": result["properties"]["title"],
            "sheets": [
                {
                    "title": s["properties"]["title"],
                    "index": s["properties"]["index"],
                    "rows": s["properties"].get("gridProperties", {}).get("rowCount", 0),
                    "cols": s["properties"].get("gridProperties", {}).get("columnCount", 0),
                }
                for s in result.get("sheets", [])
            ],
            "url": f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit",
        }

    def clear(self, spreadsheet_id: str, range_: str) -> dict:
        """Clear values in a range."""
        result = self._service.spreadsheets().values().clear(
            spreadsheetId=spreadsheet_id, range=range_, body={}
        ).execute()
        log.info(f"Cleared {range_}")
        return result

    def list_recent(self, max_results: int = 10) -> list[dict]:
        """List recently modified spreadsheets."""
        result = self._drive.files().list(
            q="mimeType='application/vnd.google-apps.spreadsheet' and trashed=false",
            pageSize=max_results,
            orderBy="modifiedTime desc",
            fields="files(id,name,modifiedTime,webViewLink)",
        ).execute()
        return result.get("files", [])

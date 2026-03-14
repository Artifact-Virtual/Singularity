"""
Google Slides service — list, read, create.

Usage:
    slides = SlidesService(creds)
    presentations = slides.list_recent()
    content = slides.read("presentation_id")
    pres = slides.create("My Presentation")
"""
from __future__ import annotations

import logging
from typing import Optional

from googleapiclient.discovery import build

log = logging.getLogger("singularity.workspace.slides")


class SlidesService:
    """Google Slides API wrapper."""

    def __init__(self, creds):
        self._service = build("slides", "v1", credentials=creds)
        self._drive = build("drive", "v3", credentials=creds)

    def create(self, title: str) -> dict:
        """Create a new presentation."""
        result = self._service.presentations().create(
            body={"title": title}
        ).execute()
        pid = result["presentationId"]
        log.info(f"Presentation created: {title} → {pid}")
        return {
            "id": pid,
            "title": title,
            "url": f"https://docs.google.com/presentation/d/{pid}/edit",
        }

    def read(self, presentation_id: str) -> dict:
        """
        Read a presentation's content.
        
        Returns title, slide count, and text content from each slide.
        """
        pres = self._service.presentations().get(
            presentationId=presentation_id
        ).execute()

        slides_data = []
        for i, slide in enumerate(pres.get("slides", [])):
            texts = []
            for element in slide.get("pageElements", []):
                shape = element.get("shape", {})
                text_content = shape.get("text", {})
                for text_elem in text_content.get("textElements", []):
                    run = text_elem.get("textRun", {})
                    if run.get("content", "").strip():
                        texts.append(run["content"].strip())
            slides_data.append({
                "slide_number": i + 1,
                "object_id": slide.get("objectId", ""),
                "text": "\n".join(texts),
            })

        return {
            "id": presentation_id,
            "title": pres.get("title", ""),
            "slide_count": len(pres.get("slides", [])),
            "slides": slides_data,
            "url": f"https://docs.google.com/presentation/d/{presentation_id}/edit",
        }

    def add_slide(self, presentation_id: str, layout: str = "BLANK") -> dict:
        """
        Add a new slide to a presentation.
        
        Args:
            presentation_id: Presentation ID.
            layout: Slide layout (BLANK, TITLE, TITLE_AND_BODY, etc.).
        """
        requests = [
            {
                "createSlide": {
                    "slideLayoutReference": {"predefinedLayout": layout},
                }
            }
        ]
        result = self._service.presentations().batchUpdate(
            presentationId=presentation_id, body={"requests": requests}
        ).execute()
        log.info(f"Added slide to presentation {presentation_id}")
        return result

    def add_text(self, presentation_id: str, slide_object_id: str, text: str) -> dict:
        """Add a text box with content to a slide."""
        # Create a text box shape
        requests = [
            {
                "createShape": {
                    "objectId": f"textbox_{slide_object_id}",
                    "shapeType": "TEXT_BOX",
                    "elementProperties": {
                        "pageObjectId": slide_object_id,
                        "size": {
                            "height": {"magnitude": 300, "unit": "PT"},
                            "width": {"magnitude": 500, "unit": "PT"},
                        },
                        "transform": {
                            "scaleX": 1,
                            "scaleY": 1,
                            "translateX": 50,
                            "translateY": 100,
                            "unit": "PT",
                        },
                    },
                }
            },
            {
                "insertText": {
                    "objectId": f"textbox_{slide_object_id}",
                    "text": text,
                    "insertionIndex": 0,
                }
            },
        ]
        result = self._service.presentations().batchUpdate(
            presentationId=presentation_id, body={"requests": requests}
        ).execute()
        return result

    def export(self, presentation_id: str, output_path: str, mime_type: str = "application/pdf") -> str:
        """Export presentation to PDF or PPTX."""
        from pathlib import Path
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        content = self._drive.files().export(
            fileId=presentation_id, mimeType=mime_type
        ).execute()
        target.write_bytes(content)
        log.info(f"Exported presentation {presentation_id} → {target}")
        return str(target)

    def list_recent(self, max_results: int = 10) -> list[dict]:
        """List recently modified presentations."""
        result = self._drive.files().list(
            q="mimeType='application/vnd.google-apps.presentation' and trashed=false",
            pageSize=max_results,
            orderBy="modifiedTime desc",
            fields="files(id,name,modifiedTime,webViewLink)",
        ).execute()
        return result.get("files", [])

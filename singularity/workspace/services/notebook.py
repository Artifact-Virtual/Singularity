"""
NotebookLM-style podcast and content generation.

Uses Google Gemini API to generate podcast-style audio discussions,
summaries, and analyses from research papers and documents.

Usage:
    notebook = NotebookService(creds)
    
    # Generate a podcast script from research papers
    script = notebook.generate_podcast_script(
        sources=["paper1.md", "paper2.md"],
        style="conversational",
        duration_minutes=10,
    )
    
    # Generate audio using Gemini TTS
    audio = notebook.generate_audio(script, output_path="podcast.wav")
    
    # Summarize documents
    summary = notebook.summarize(["paper.md"], style="executive")
    
    # Generate study guide / FAQ
    faq = notebook.generate_faq(["paper.md"])
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

log = logging.getLogger("singularity.workspace.notebook")

# Default Gemini API key location
GEMINI_KEY_PATH = Path.home() / ".singularity" / "gemini_api_key"


class NotebookService:
    """
    NotebookLM-style content generation powered by Gemini.
    
    Supports:
    - Podcast script generation from multiple sources
    - Audio synthesis via Gemini TTS
    - Document summarization
    - FAQ / study guide generation
    - Briefing document creation
    """

    def __init__(self, creds=None, api_key: Optional[str] = None):
        self._creds = creds
        self._api_key = api_key or self._load_api_key()
        self._client = None

    def _load_api_key(self) -> Optional[str]:
        """Load Gemini API key from env or file."""
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if key:
            return key
        if GEMINI_KEY_PATH.exists():
            return GEMINI_KEY_PATH.read_text().strip()
        return None

    def _get_client(self):
        """Get or create the Gemini client."""
        if self._client:
            return self._client

        from google import genai

        if self._api_key:
            self._client = genai.Client(api_key=self._api_key)
        else:
            # Use OAuth credentials via application default
            self._client = genai.Client()

        return self._client

    def _load_sources(self, sources: list[str]) -> list[dict]:
        """
        Load source documents from file paths or text.
        
        Each source can be:
        - A file path (reads the file)
        - A URL starting with http (fetches the URL)
        - Raw text (used as-is)
        """
        loaded = []
        for source in sources:
            path = Path(source)
            if path.exists():
                content = path.read_text(errors="replace")
                loaded.append({
                    "name": path.name,
                    "content": content[:50000],  # Limit per source
                    "type": "file",
                })
            elif source.startswith("http"):
                try:
                    import urllib.request
                    with urllib.request.urlopen(source, timeout=10) as resp:
                        content = resp.read().decode("utf-8", errors="replace")
                    loaded.append({
                        "name": source.split("/")[-1],
                        "content": content[:50000],
                        "type": "url",
                    })
                except Exception as e:
                    log.warning(f"Failed to fetch {source}: {e}")
            else:
                loaded.append({
                    "name": "inline",
                    "content": source[:50000],
                    "type": "text",
                })
        return loaded

    def generate_podcast_script(
        self,
        sources: list[str],
        style: str = "conversational",
        duration_minutes: int = 10,
        hosts: int = 2,
        audience: str = "technical but accessible",
        focus: Optional[str] = None,
    ) -> dict:
        """
        Generate a podcast script from source documents.
        
        Args:
            sources: List of file paths, URLs, or text to base the podcast on.
            style: Script style (conversational, interview, lecture, debate).
            duration_minutes: Target podcast duration.
            hosts: Number of hosts/speakers (1-3).
            audience: Target audience description.
            focus: Specific aspects to focus on (optional).
            
        Returns:
            Dict with 'script', 'title', 'description', 'segments'.
        """
        loaded = self._load_sources(sources)
        if not loaded:
            raise ValueError("No valid sources provided")

        source_text = "\n\n---\n\n".join(
            f"SOURCE: {s['name']}\n{s['content']}" for s in loaded
        )

        # Estimate words for target duration (~150 words/minute for podcast)
        target_words = duration_minutes * 150

        speaker_names = ["Host A", "Host B", "Host C"][:hosts]

        prompt = f"""You are a world-class podcast producer. Generate a natural, engaging podcast script 
based on the following source material.

STYLE: {style}
TARGET DURATION: {duration_minutes} minutes (~{target_words} words)
SPEAKERS: {', '.join(speaker_names)}
AUDIENCE: {audience}
{f'FOCUS: {focus}' if focus else ''}

REQUIREMENTS:
- Make it feel like a real conversation, not a reading
- Include natural transitions, reactions, and follow-up questions
- Explain complex concepts with analogies and examples
- Start with a compelling hook
- End with key takeaways
- Format each line as: SPEAKER: dialogue
- Include [PAUSE], [LAUGH], [EMPHASIS] markers for natural delivery
- Be accurate to the source material — don't fabricate claims

SOURCE MATERIAL:
{source_text}

Generate the complete podcast script now. After the script, provide:
TITLE: (a catchy podcast episode title)
DESCRIPTION: (a 2-3 sentence episode description)
"""

        client = self._get_client()
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )

        script_text = response.text

        # Parse title and description from the end
        title = "Research Deep Dive"
        description = ""
        lines = script_text.strip().split("\n")
        for i, line in enumerate(lines):
            if line.startswith("TITLE:"):
                title = line[6:].strip()
            elif line.startswith("DESCRIPTION:"):
                description = line[12:].strip()

        return {
            "script": script_text,
            "title": title,
            "description": description,
            "sources": [s["name"] for s in loaded],
            "target_duration_minutes": duration_minutes,
            "style": style,
        }

    def generate_audio(
        self,
        script: str,
        output_path: str = "podcast.wav",
        voice: str = "Kore",
    ) -> Optional[Path]:
        """
        Generate audio from a podcast script using Gemini TTS.
        
        Args:
            script: The podcast script text.
            output_path: Where to save the audio file.
            voice: Voice preset name for Gemini TTS.
            
        Returns:
            Path to the generated audio file, or None if TTS unavailable.
        """
        try:
            from google.genai import types
            
            client = self._get_client()
            
            response = client.models.generate_content(
                model="gemini-2.5-flash-preview-tts",
                contents=script,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=voice,
                            )
                        )
                    ),
                ),
            )
            
            target = Path(output_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            
            # Extract audio data
            audio_data = response.candidates[0].content.parts[0].inline_data.data
            
            import wave
            import struct
            
            with wave.open(str(target), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(24000)
                wf.writeframes(audio_data)
            
            log.info(f"Audio generated: {target} ({target.stat().st_size} bytes)")
            return target
            
        except Exception as e:
            log.warning(f"TTS generation failed: {e}")
            log.info("Falling back to script-only output")
            # Save script as text fallback
            target = Path(output_path).with_suffix(".txt")
            target.write_text(script)
            return target

    def generate_multi_speaker_audio(
        self,
        script: str,
        output_path: str = "podcast.wav",
        voice_a: str = "Kore",
        voice_b: str = "Puck",
    ) -> Optional[Path]:
        """
        Generate multi-speaker audio from a podcast script.
        
        Splits script by speaker markers and generates audio for each,
        then concatenates. Falls back to single-voice if multi not available.
        
        Args:
            script: Script with "Host A:" and "Host B:" markers.
            output_path: Where to save the audio file.
            voice_a: Voice for Host A.
            voice_b: Voice for Host B.
        """
        try:
            from google.genai import types
            
            client = self._get_client()
            
            # Use multi-speaker TTS prompt
            tts_prompt = f"""Read this podcast script with two distinct voices.
Use a natural conversational tone with appropriate pauses and emphasis.

{script}"""
            
            response = client.models.generate_content(
                model="gemini-2.5-flash-preview-tts",
                contents=tts_prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(
                            speaker_voice_configs=[
                                types.SpeakerVoiceConfig(
                                    speaker="Host A",
                                    voice_config=types.VoiceConfig(
                                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                            voice_name=voice_a
                                        )
                                    ),
                                ),
                                types.SpeakerVoiceConfig(
                                    speaker="Host B",
                                    voice_config=types.VoiceConfig(
                                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                            voice_name=voice_b
                                        )
                                    ),
                                ),
                            ]
                        )
                    ),
                ),
            )
            
            target = Path(output_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            
            audio_data = response.candidates[0].content.parts[0].inline_data.data
            
            import wave
            with wave.open(str(target), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(24000)
                wf.writeframes(audio_data)
            
            log.info(f"Multi-speaker audio generated: {target}")
            return target
            
        except Exception as e:
            log.warning(f"Multi-speaker TTS failed: {e}, falling back to single voice")
            return self.generate_audio(script, output_path)

    def summarize(
        self,
        sources: list[str],
        style: str = "executive",
        max_length: int = 500,
    ) -> str:
        """
        Summarize source documents.
        
        Args:
            sources: List of file paths, URLs, or text.
            style: Summary style (executive, technical, casual, academic).
            max_length: Target summary length in words.
        """
        loaded = self._load_sources(sources)
        source_text = "\n\n---\n\n".join(
            f"SOURCE: {s['name']}\n{s['content']}" for s in loaded
        )

        prompt = f"""Summarize the following material in a {style} style.
Target length: ~{max_length} words.
Be accurate. Don't fabricate.

{source_text}"""

        client = self._get_client()
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        return response.text

    def generate_faq(self, sources: list[str], num_questions: int = 10) -> list[dict]:
        """
        Generate FAQ / study guide from sources.
        
        Returns list of {question, answer} dicts.
        """
        loaded = self._load_sources(sources)
        source_text = "\n\n---\n\n".join(
            f"SOURCE: {s['name']}\n{s['content']}" for s in loaded
        )

        prompt = f"""Based on the following material, generate {num_questions} frequently asked questions
with detailed answers. Format as JSON array of objects with "question" and "answer" keys.

{source_text}

Return ONLY valid JSON. No markdown code fences."""

        client = self._get_client()
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )

        try:
            text = response.text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            return json.loads(text)
        except json.JSONDecodeError:
            return [{"question": "Parse error", "answer": response.text}]

    def generate_briefing(
        self,
        sources: list[str],
        topic: str,
        audience: str = "executive leadership",
    ) -> str:
        """
        Generate a briefing document from sources.
        
        Args:
            sources: Source material.
            topic: Briefing topic.
            audience: Target audience.
        """
        loaded = self._load_sources(sources)
        source_text = "\n\n---\n\n".join(
            f"SOURCE: {s['name']}\n{s['content']}" for s in loaded
        )

        prompt = f"""Create a professional briefing document on: {topic}

Target audience: {audience}

Structure:
1. Executive Summary (3-4 sentences)
2. Key Findings (bullet points)
3. Analysis (2-3 paragraphs)
4. Implications (what this means)
5. Recommended Actions

Be accurate to the source material. Cite specific findings.

SOURCE MATERIAL:
{source_text}"""

        client = self._get_client()
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        return response.text

    @staticmethod
    def available_voices() -> list[str]:
        """List available TTS voice presets."""
        return [
            "Zephyr",   # Bright
            "Puck",     # Upbeat  
            "Charon",   # Informative
            "Kore",     # Firm
            "Fenrir",   # Excitable
            "Leda",     # Youthful
            "Orus",     # Firm
            "Aoede",    # Breezy
            "Callirrhoe",  # Easy-going
            "Autonoe",  # Bright
        ]

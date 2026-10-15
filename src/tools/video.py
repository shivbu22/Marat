"""Video and audio ingestion engine for MARAT.

Extracts speech from lecture videos, symposium talks, and research podcasts.
Supports fast caption extraction for YouTube and local Whisper ASR for
offline video/audio recordings.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


def _ensure_ffmpeg() -> bool:
    """Make sure ffmpeg is discoverable in PATH, pulling bundled binary if needed."""
    if shutil.which("ffmpeg"):
        return True
    try:
        import imageio_ffmpeg

        exe = Path(imageio_ffmpeg.get_ffmpeg_exe())
        bin_dir = exe.parent
        target = bin_dir / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        if not target.exists():
            shutil.copyfile(exe, target)
        os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
        return bool(shutil.which("ffmpeg"))
    except Exception:
        return False


def _format_timestamp(seconds: float) -> str:
    """Convert float seconds to MM:SS or HH:MM:SS string."""
    s = int(seconds)
    hours = s // 3600
    minutes = (s % 3600) // 60
    secs = s % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def extract_youtube_id(url: str) -> str | None:
    """Extract 11-char YouTube ID from typical URL formats."""
    patterns = [
        r"(?:v=|\/v\/|youtu\.be\/|\/embed\/|\/shorts\/)([a-zA-Z0-9_-]{11})",
        r"^([a-zA-Z0-9_-]{11})$",
    ]
    for pattern in patterns:
        match = re.search(pattern, url.strip())
        if match:
            return match.group(1)
    return None


class TranscriptSegment(BaseModel):
    start: float
    end: float
    timestamp: str
    text: str


class VideoLecture(BaseModel):
    title: str
    url: str
    duration_seconds: float = 0.0
    segments: list[TranscriptSegment] = Field(default_factory=list)
    full_text: str = ""
    source_type: str = "youtube"


def fetch_youtube_captions(video_id: str) -> list[TranscriptSegment] | None:
    """Attempt fast caption extraction via youtube-transcript-api."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        ytt = YouTubeTranscriptApi()
        if hasattr(ytt, "fetch"):
            fetched = ytt.fetch(video_id, languages=["en", "en-US", "en-GB"])
            raw = fetched.to_raw_data() if hasattr(fetched, "to_raw_data") else list(fetched)
        elif hasattr(YouTubeTranscriptApi, "get_transcript"):
            raw = YouTubeTranscriptApi.get_transcript(video_id, languages=["en", "en-US", "en-GB"])
        else:
            raw = []

        return [
            TranscriptSegment(
                start=float(entry.get("start", 0.0)),
                end=float(entry.get("start", 0.0)) + float(entry.get("duration", 0.0)),
                timestamp=_format_timestamp(float(entry.get("start", 0.0))),
                text=entry["text"].strip(),
            )
            for entry in raw
            if entry.get("text", "").strip()
        ] or None
    except Exception:
        return None


def download_audio_track(url: str, output_dir: Path) -> tuple[Path | None, dict[str, Any]]:
    """Download audio from video URL using yt-dlp. Returns (audio_path, metadata)."""
    _ensure_ffmpeg()
    try:
        import yt_dlp

        out_template = str(output_dir / "%(id)s.%(ext)s")
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": out_template,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "128",
                }
            ],
            "quiet": True,
            "no_warnings": True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if not info:
                return None, {}
            video_id = info.get("id", "audio")
            mp3_path = output_dir / f"{video_id}.mp3"
            if mp3_path.exists():
                return mp3_path, info
            # Check if any audio file matches pattern
            for f in output_dir.glob(f"{video_id}.*"):
                return f, info
            return None, info
    except Exception as e:
        print(f"[VideoIngest] yt-dlp error: {e}")
        return None, {}


def transcribe_local_audio(
    audio_path: Path, model_size: str = "base"
) -> list[TranscriptSegment]:
    """Transcribe audio file using OpenAI Whisper locally."""
    _ensure_ffmpeg()
    try:
        import whisper

        model = whisper.load_model(model_size)
        result = model.transcribe(str(audio_path), fp16=False)
        return [
            TranscriptSegment(
                start=float(seg.get("start", 0.0)),
                end=float(seg.get("end", 0.0)),
                timestamp=_format_timestamp(float(seg.get("start", 0.0))),
                text=seg["text"].strip(),
            )
            for seg in result.get("segments", [])
            if seg.get("text", "").strip()
        ]
    except Exception as e:
        print(f"[VideoIngest] Whisper error: {e}")
        return []


def ingest_video(
    source: str, title: str = "", whisper_model: str = "base"
) -> VideoLecture | None:
    """Ingest lecture from YouTube URL or local video/audio file.
    
    1. Checks if source is a YouTube link.
    2. Tries fast caption extraction first (no heavy download).
    3. Falls back to yt-dlp download + Whisper transcription.
    4. If local file path, runs Whisper directly.
    """
    local_path = Path(source)
    if local_path.exists() and local_path.is_file():
        segs = transcribe_local_audio(local_path, model_size=whisper_model)
        full = " ".join(s.text for s in segs)
        duration = segs[-1].end if segs else 0.0
        return VideoLecture(
            title=title or local_path.stem,
            url=str(local_path.resolve()),
            duration_seconds=duration,
            segments=segs,
            full_text=full,
            source_type="local_file",
        )

    yt_id = extract_youtube_id(source)
    if yt_id:
        url = f"https://www.youtube.com/watch?v={yt_id}"
        # Strategy 1: Instant captions API
        captions = fetch_youtube_captions(yt_id)
        if captions:
            full = " ".join(c.text for c in captions)
            duration = captions[-1].end if captions else 0.0
            return VideoLecture(
                title=title or f"YouTube Lecture ({yt_id})",
                url=url,
                duration_seconds=duration,
                segments=captions,
                full_text=full,
                source_type="youtube_captions",
            )

        # Strategy 2: Download audio track + Whisper
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_file, meta = download_audio_track(url, Path(tmpdir))
            if audio_file and audio_file.exists():
                segs = transcribe_local_audio(audio_file, model_size=whisper_model)
                full = " ".join(s.text for s in segs)
                return VideoLecture(
                    title=title or meta.get("title", f"YouTube Lecture ({yt_id})"),
                    url=url,
                    duration_seconds=float(meta.get("duration", segs[-1].end if segs else 0.0)),
                    segments=segs,
                    full_text=full,
                    source_type="youtube_whisper",
                )

    return None


def chunk_transcript_with_timestamps(
    lecture: VideoLecture, window_seconds: float = 60.0
) -> list[tuple[str, str]]:
    """Group segments into ~60-second semantic blocks with timestamp citations.
    
    Returns list of (timestamp_tag, chunk_text).
    Example: ("[02:15]", "[02:15] Neural networks require activation functions...")
    """
    if not lecture.segments:
        return []

    chunks: list[tuple[str, str]] = []
    current_text: list[str] = []
    current_start = lecture.segments[0].start
    current_ts = lecture.segments[0].timestamp

    for seg in lecture.segments:
        current_text.append(seg.text)
        if (seg.end - current_start) >= window_seconds:
            block = f"[{current_ts}] " + " ".join(current_text)
            chunks.append((current_ts, block))
            current_text = []
            current_start = seg.end
            current_ts = seg.timestamp

    if current_text:
        block = f"[{current_ts}] " + " ".join(current_text)
        chunks.append((current_ts, block))

    return chunks


def index_lecture_in_rag(lecture: VideoLecture, collection_name: str = "research_vault") -> int:
    """Index timestamped video lecture blocks into ChromaDB vault."""
    from ..rag.store import get_rag

    rag = get_rag()
    blocks = chunk_transcript_with_timestamps(lecture)
    if not blocks:
        return 0

    texts = [b[1] for b in blocks]
    metadatas = [
        {
            "source": lecture.url,
            "title": lecture.title,
            "timestamp": b[0],
            "type": "video_lecture",
        }
        for b in blocks
    ]
    return rag.add_texts(texts=texts, metadatas=metadatas, collection_name=collection_name)


def generate_fallback_summary(lecture: VideoLecture, focus: str = "") -> str:
    """Generate structured extractive summary if LLM call is offline or unavailable."""
    blocks = chunk_transcript_with_timestamps(lecture, window_seconds=90.0)
    dur_str = _format_timestamp(lecture.duration_seconds)
    
    # Key timestamp chapters (sample evenly up to 6 chapters)
    step = max(1, len(blocks) // 6)
    chapter_highlights = blocks[::step][:6]
    
    chapters_md = "\n".join(
        f"- **`{ts}`** {text[len(ts)+3:len(ts)+160].strip()}..."
        for ts, text in chapter_highlights
    )

    overview = lecture.full_text[:600].strip() + "..." if len(lecture.full_text) > 600 else lecture.full_text

    return (
        f"## 📺 Video Summary: {lecture.title}\n\n"
        f"**Source:** [{lecture.url}]({lecture.url}) · **Duration:** {dur_str} · **Transcription:** `{lecture.source_type}`\n\n"
        f"### 📌 Executive Overview\n"
        f"{overview}\n\n"
        f"### ⏱️ Timestamped Chapters & Highlights\n"
        f"{chapters_md or '- Continuous lecture without explicit segment boundaries.'}\n\n"
        f"### 💡 Key Takeaways\n"
        f"- Complete transcript extracted and indexed into Marat's vector memory ({len(blocks)} chunks).\n"
        f"- You can ask specific follow-up questions about any concept or timestamp in this video directly in this chat!"
    )


async def summarize_youtube_video(
    url: str, focus: str = "", workspace_id: str = "default"
) -> dict[str, Any]:
    """Ingest, index, and synthesize an executive summary of any YouTube video."""
    lecture = ingest_video(url)
    if not lecture:
        return {
            "status": "error",
            "message": f"Could not extract transcript or audio from YouTube URL: {url}. Please ensure the video is public and has captions or downloadable audio.",
        }

    # 1. Index into global RAG vault
    indexed_chunks = index_lecture_in_rag(lecture, collection_name="research_vault")

    # 2. Also index into workspace vault if workspace specified
    if workspace_id:
        try:
            from ..workspaces.manager import get_workspace_manager
            from ..rag.store import get_rag
            mgr = get_workspace_manager()
            rag = get_rag()
            ws = mgr.get_workspace(workspace_id)
            if ws and ws.vector_collection:
                doc_name = f"YouTube_{lecture.title[:40].replace(' ', '_')}.txt"
                doc, chunks = mgr.add_document(
                    workspace_id,
                    doc_name,
                    lecture.full_text.encode("utf-8"),
                    extra_metadata={"url": lecture.url, "source": "youtube", "type": "video_lecture"},
                )
                rag.add_chunks(chunks, collection_name=ws.vector_collection)
        except Exception:
            pass

    # 3. Generate summary via LLM if available, else fallback
    summary_text = ""
    try:
        from ..llm import get_llm
        from langchain_core.messages import HumanMessage, SystemMessage
        
        llm = get_llm(temperature=0.2)
        sample_transcript = lecture.full_text[:7000]
        dur_str = _format_timestamp(lecture.duration_seconds)
        
        blocks = chunk_transcript_with_timestamps(lecture, window_seconds=75.0)
        sample_timestamps = "\n".join(f"{ts}: {txt[:120]}..." for ts, txt in blocks[:8])

        prompt = (
            f"You are Marat, an elite multimedia intelligence assistant.\n"
            f"Summarize the following YouTube video transcript.\n\n"
            f"Video Title: {lecture.title}\n"
            f"Duration: {dur_str}\n"
            f"URL: {lecture.url}\n"
            f"{'User Focus: ' + focus if focus else ''}\n\n"
            f"Sample Timestamped Moments:\n{sample_timestamps}\n\n"
            f"Transcript Content:\n{sample_transcript}\n\n"
            f"Provide a structured, engaging Markdown summary with:\n"
            f"1. Executive Overview (2-3 concise paragraphs)\n"
            f"2. Core Concepts & Takeaways (bulleted, clear)\n"
            f"3. Timestamped Chapter Breakdown\n"
            f"4. Discussion & Follow-up questions the user can ask."
        )
        res = await llm.ainvoke([SystemMessage(content="You are an expert research assistant."), HumanMessage(content=prompt)])
        summary_text = res.content if hasattr(res, "content") else str(res)
    except Exception:
        summary_text = generate_fallback_summary(lecture, focus=focus)

    return {
        "status": "success",
        "title": lecture.title,
        "url": lecture.url,
        "duration_seconds": lecture.duration_seconds,
        "duration_formatted": _format_timestamp(lecture.duration_seconds),
        "source_type": lecture.source_type,
        "indexed_chunks": indexed_chunks,
        "summary": summary_text,
    }

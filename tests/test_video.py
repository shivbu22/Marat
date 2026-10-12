"""Tests for video lecture transcription and ingestion module."""

from unittest.mock import MagicMock, patch

from src.tools.video import (
    TranscriptSegment,
    VideoLecture,
    _format_timestamp,
    chunk_transcript_with_timestamps,
    extract_youtube_id,
    index_lecture_in_rag,
    ingest_video,
)


def test_extract_youtube_id():
    assert extract_youtube_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_youtube_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_youtube_id("https://www.youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_youtube_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_youtube_id("https://example.com/not-youtube") is None


def test_format_timestamp():
    assert _format_timestamp(45.0) == "00:45"
    assert _format_timestamp(125.0) == "02:05"
    assert _format_timestamp(3665.0) == "01:01:05"


def test_chunk_transcript_with_timestamps():
    lecture = VideoLecture(
        title="Attention Mechanism Lecture",
        url="https://youtube.com/watch?v=test1234567",
        segments=[
            TranscriptSegment(start=0.0, end=15.0, timestamp="00:00", text="Welcome to deep learning."),
            TranscriptSegment(start=15.0, end=40.0, timestamp="00:15", text="Today we discuss self-attention."),
            TranscriptSegment(start=40.0, end=75.0, timestamp="00:40", text="Keys, queries, and values."),
        ],
    )
    chunks = chunk_transcript_with_timestamps(lecture, window_seconds=30.0)
    assert len(chunks) >= 2
    # First chunk starts at 00:00
    assert chunks[0][0] == "00:00"
    assert "[00:00]" in chunks[0][1]
    assert "Welcome to deep learning" in chunks[0][1]


def test_ingest_video_with_captions():
    mock_segs = [
        TranscriptSegment(start=0.0, end=5.0, timestamp="00:00", text="Neural networks"),
        TranscriptSegment(start=5.0, end=15.0, timestamp="00:05", text="Gradient descent"),
    ]
    with patch("src.tools.video.fetch_youtube_captions", return_value=mock_segs):
        lecture = ingest_video("https://www.youtube.com/watch?v=kCc8FmEb1nY", title="CS229")
        assert lecture is not None
        assert lecture.title == "CS229"
        assert len(lecture.segments) == 2
        assert lecture.segments[0].timestamp == "00:00"
        assert lecture.segments[1].timestamp == "00:05"
        assert "Gradient descent" in lecture.full_text


def test_index_lecture_in_rag():
    mock_rag = MagicMock()
    mock_rag.add_texts.return_value = 2

    lecture = VideoLecture(
        title="Test Lecture",
        url="https://youtube.com/watch?v=test1234567",
        segments=[
            TranscriptSegment(start=0.0, end=20.0, timestamp="00:00", text="Part one."),
            TranscriptSegment(start=20.0, end=40.0, timestamp="00:20", text="Part two."),
        ],
    )

    with patch("src.rag.store.get_rag", return_value=mock_rag):
        count = index_lecture_in_rag(lecture)
        assert count == 2
        mock_rag.add_texts.assert_called_once()


def test_ingest_local_audio_file(tmp_path):
    import wave

    audio_file = tmp_path / "sample.wav"
    with wave.open(str(audio_file), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 16000)

    lecture = ingest_video(str(audio_file), title="Local Audio Test", whisper_model="tiny")
    assert lecture is not None
    assert lecture.title == "Local Audio Test"
    assert lecture.source_type == "local_file"


def test_invalid_video_source():
    assert ingest_video("https://not-a-real-website.example.org/fake") is None

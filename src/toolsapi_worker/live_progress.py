from __future__ import annotations

import re
from typing import Any


_TIMESTAMP_LINE = re.compile(
    r"^\[(?P<start>\d{2}:\d{2}(?::\d{2})?\.\d{3})\s+-->\s+(?P<end>\d{2}:\d{2}(?::\d{2})?\.\d{3})\]\s*(?P<text>.*)$"
)


def timestamp_seconds(value: str) -> float:
    parts = value.split(":")
    if len(parts) == 2:
        hours = 0
        minutes = int(parts[0])
        seconds = float(parts[1])
    elif len(parts) == 3:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = float(parts[2])
    else:
        raise ValueError(f"Unsupported Whisper timestamp: {value!r}")
    return (hours * 3600) + (minutes * 60) + seconds


class MlxVerboseTranscriptCapture:
    """Capture mlx-whisper's verbose segment stream without logging transcript text locally."""

    encoding = "utf-8"

    def __init__(self, heartbeat: Any) -> None:
        self.heartbeat = heartbeat
        self._buffer = ""
        self.segments: list[dict[str, Any]] = []

    def write(self, value: str) -> int:
        text = str(value or "")
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._consume_line(line.rstrip("\r"))
        return len(text)

    def flush(self) -> None:
        return None

    def finish(self) -> None:
        if self._buffer:
            self._consume_line(self._buffer.rstrip("\r"))
            self._buffer = ""

    def isatty(self) -> bool:
        return False

    def _consume_line(self, line: str) -> None:
        match = _TIMESTAMP_LINE.match(line.strip())
        if not match:
            return

        text = match.group("text").strip()
        if not text:
            return

        start = timestamp_seconds(match.group("start"))
        end = timestamp_seconds(match.group("end"))
        if end <= start:
            return

        segment = {
            "start": round(start, 3),
            "end": round(end, 3),
            "text": text,
        }
        self.segments.append(segment)
        transcript = " ".join(str(item["text"]) for item in self.segments).strip()
        coarse_progress = min(93, 20 + len(self.segments))
        self.heartbeat.update(
            coarse_progress,
            "Transcribing",
            f"{end:.1f} seconds transcribed · {len(self.segments)} segments received.",
        )
        self.heartbeat.update_transcript(transcript, self.segments)

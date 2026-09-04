from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"Expected documentation anchor missing in {path}: {old[:80]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "README.md",
    "10. Remove local temporary media after the ownership lifecycle ends.\n\nA diarization failure does not discard a successful transcript.",
    "10. Remove local temporary media after the ownership lifecycle ends.\n\nWhile Whisper is running, workers publish bounded cumulative live transcript text and timestamped segments through the existing progress endpoint. `faster-whisper` publishes from its segment iterator; Apple Silicon MLX captures `mlx-whisper`'s incremental timestamp output without writing transcript content to local worker logs. ToolsAPI can therefore show real transcript evidence and derive progress from the latest completed audio timestamp before terminal completion.\n\nA diarization failure does not discard a successful transcript.",
)

replace_once(
    "README.md",
    "The heartbeat is independent from Whisper/pyannote progress and remains active through terminal acknowledgement and transient terminal retries. A worker stops refreshing the lease only after ToolsAPI accepts completion/failure or definitively rejects ownership, preventing a finished job from losing its lease while the final API response is unresolved.\n",
    "The heartbeat is independent from Whisper/pyannote progress and remains active through terminal acknowledgement and transient terminal retries. A worker stops refreshing the lease only after ToolsAPI accepts completion/failure or definitively rejects ownership, preventing a finished job from losing its lease while the final API response is unresolved.\n\nLive transcript snapshots are additive progress data, not terminal state. They are bounded and sent only from the current lease while new segment evidence is produced; the final `/complete` payload remains authoritative.\n",
)

replace_once(
    "CHANGELOG.md",
    "- Keep the independent Whisper lease heartbeat active while transcript completion, failure, or diarization-only terminal acknowledgement is unresolved. Transient terminal retries now retain lease freshness and the occupied worker slot until ToolsAPI accepts the exact payload or definitively rejects ownership; a completion HTTP 409 lease loss cannot fall through into a conflicting failure submission. Fixes #37.\n",
    "- Keep the independent Whisper lease heartbeat active while transcript completion, failure, or diarization-only terminal acknowledgement is unresolved. Transient terminal retries now retain lease freshness and the occupied worker slot until ToolsAPI accepts the exact payload or definitively rejects ownership; a completion HTTP 409 lease loss cannot fall through into a conflicting failure submission. Fixes #37.\n- Remote Whisper now publishes bounded cumulative live transcript text and timestamped segments while transcription is still running. `faster-whisper` streams from its segment iterator and Apple Silicon MLX captures incremental timestamp output, allowing ToolsAPI to show real transcript evidence and progress before terminal completion without writing transcript content to worker logs. Fixes #39.\n",
)

Path(".github/scripts/patch-39-docs.py").unlink(missing_ok=True)
Path(".github/workflows/one-shot-39-docs.yml").unlink(missing_ok=True)

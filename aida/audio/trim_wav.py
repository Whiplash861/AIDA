from __future__ import annotations
import wave
from pathlib import Path
from typing import Tuple

def _rms16(frames: bytes) -> float:
    # 16-bit mono/stereo little-endian RMS
    import struct, math
    if not frames:
        return 0.0
    count = len(frames) // 2
    samples = struct.unpack("<" + "h" * count, frames)
    s2 = sum(x * x for x in samples)
    return math.sqrt(s2 / max(1, count))

def trim_trailing_silence(
    in_path: Path,
    out_path: Path,
    silence_rms_threshold: float = 200.0,
    tail_padding_ms: int = 60,
    chunk_ms: int = 20,
) -> Tuple[Path, int]:
    """
    Trims trailing silence from a WAV and returns (out_path, trimmed_ms).
    Keeps a small tail padding so the cut doesn't click.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with wave.open(str(in_path), "rb") as wf:
        nch = wf.getnchannels()
        sw = wf.getsampwidth()
        fr = wf.getframerate()
        nframes = wf.getnframes()

        if sw != 2:
            # Only trim 16-bit WAVs (your files are)
            out_path.write_bytes(in_path.read_bytes())
            return out_path, 0

        frames = wf.readframes(nframes)

    bytes_per_frame = nch * sw
    chunk_frames = int(fr * (chunk_ms / 1000.0))
    chunk_bytes = chunk_frames * bytes_per_frame

    # walk backwards in chunks
    cut_index = len(frames)
    i = len(frames)

    while i > 0:
        start = max(0, i - chunk_bytes)
        chunk = frames[start:i]
        if _rms16(chunk) > silence_rms_threshold:
            cut_index = i
            break
        i = start

    pad_frames = int(fr * (tail_padding_ms / 1000.0))
    pad_bytes = pad_frames * bytes_per_frame
    new_len = min(len(frames), cut_index + pad_bytes)

    trimmed_ms = int((len(frames) - new_len) / bytes_per_frame / fr * 1000)

    with wave.open(str(out_path), "wb") as out:
        out.setnchannels(nch)
        out.setsampwidth(sw)
        out.setframerate(fr)
        out.writeframes(frames[:new_len])

    return out_path, trimmed_ms

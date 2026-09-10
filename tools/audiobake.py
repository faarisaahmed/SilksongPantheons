"""
Baking Godhome's sound.

Every Godhome AudioSource points at a clip living in Hollow Knight's streamed .resource
files. UnityPy can decode those to WAV, but raw PCM is enormous - one 16-second stereo
clip is 2.8 MB - so clips are downmixed to mono, resampled to 22050 Hz and stored as
16-bit PCM. That is roughly an eighth of the size and is exactly the shape Unity's
AudioClip.Create + SetData wants on the other side, with no runtime decoder needed.

Long ambience is capped rather than skipped: a looping atmos track only needs enough to
loop over.
"""

import audioop
import io
import os
import wave

TARGET_RATE = 22050
MAX_SECONDS = 12.0     # long ambient loops get truncated to this
MUSIC_SECONDS = 400.0  # music is not an effect: a Godhome track runs three to five
                       # minutes and truncating it would cut off mid-phrase


def decode_clip(clip_obj, max_seconds=None):
    """
    (pcm16_bytes, sample_count, rate) for an AudioClip, or None.

    UnityPy hands back a WAV per clip; everything after that is plain audioop.
    """
    try:
        samples = clip_obj.read().samples
    except Exception:
        return None
    if not samples:
        return None

    wav_bytes = next(iter(samples.values()))
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as w:
            channels = w.getnchannels()
            width = w.getsampwidth()
            rate = w.getframerate()
            frames = w.readframes(w.getnframes())
    except Exception:
        return None

    if not frames:
        return None

    # 16-bit is what SetData wants; anything else converts first.
    if width != 2:
        frames = audioop.lin2lin(frames, width, 2)
        width = 2

    if channels == 2:
        frames = audioop.tomono(frames, width, 0.5, 0.5)
        channels = 1

    if rate != TARGET_RATE:
        frames, _ = audioop.ratecv(frames, width, channels, rate, TARGET_RATE, None)
        rate = TARGET_RATE

    max_bytes = int((max_seconds if max_seconds else MAX_SECONDS) * rate) * 2
    if len(frames) > max_bytes:
        frames = frames[:max_bytes]

    return frames, len(frames) // 2, rate

#!/usr/bin/env python3
"""
IMA ADPCM, so Godhome's music can travel.

Sound effects are short enough to carry as 16-bit PCM. Music is not: a Godhome track runs
three to five minutes, which is thirteen megabytes a piece at 22 kHz, and there are
several. IMA ADPCM stores four bits a sample instead of sixteen - a quarter of the size -
and on orchestral material at 22 kHz the difference is hard to hear, which is a far better
trade than halving the sample rate.

The algorithm is the standard one, and deliberately written to be transliterated: the C#
decoder in GodhomeData mirrors this function step for step, including the clamps, because
the two must agree exactly or the track turns to noise.
"""
import struct

INDEX_TABLE = [-1, -1, -1, -1, 2, 4, 6, 8, -1, -1, -1, -1, 2, 4, 6, 8]

STEP_TABLE = [
    7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45,
    50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130, 143, 157, 173, 190, 209, 230, 253,
    279, 307, 337, 371, 408, 449, 494, 544, 598, 658, 724, 796, 876, 963, 1060, 1166,
    1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327, 3660, 4026, 4428,
    4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493, 10442, 11487, 12635, 13899, 15289,
    16818, 18500, 20350, 22385, 24623, 27086, 29794, 32767,
]


def encode(pcm16):
    """16-bit mono PCM -> packed 4-bit codes, two samples per byte."""
    n = len(pcm16) // 2
    samples = struct.unpack(f"<{n}h", pcm16[:n * 2])

    out = bytearray((n + 1) // 2)
    predictor = 0
    index = 0

    for i, sample in enumerate(samples):
        step = STEP_TABLE[index]

        diff = sample - predictor
        code = 0
        if diff < 0:
            code = 8
            diff = -diff

        t = step
        if diff >= t:
            code |= 4
            diff -= t
        t >>= 1
        if diff >= t:
            code |= 2
            diff -= t
        t >>= 1
        if diff >= t:
            code |= 1

        # Decode the code we just chose, so the encoder's predictor follows exactly the
        # path the decoder will. Skipping this is the classic way to get drift.
        diffq = step >> 3
        if code & 4:
            diffq += step
        if code & 2:
            diffq += step >> 1
        if code & 1:
            diffq += step >> 2
        predictor += -diffq if code & 8 else diffq
        predictor = max(-32768, min(32767, predictor))

        index += INDEX_TABLE[code]
        index = max(0, min(88, index))

        if i & 1:
            out[i >> 1] |= code << 4
        else:
            out[i >> 1] = code

    return bytes(out)


def decode(data, sample_count):
    """The reference decoder, used to check the encoder round-trips."""
    out = []
    predictor = 0
    index = 0
    for i in range(sample_count):
        b = data[i >> 1]
        code = (b >> 4) if (i & 1) else (b & 0x0F)
        step = STEP_TABLE[index]
        diffq = step >> 3
        if code & 4:
            diffq += step
        if code & 2:
            diffq += step >> 1
        if code & 1:
            diffq += step >> 2
        predictor += -diffq if code & 8 else diffq
        predictor = max(-32768, min(32767, predictor))
        index += INDEX_TABLE[code]
        index = max(0, min(88, index))
        out.append(predictor)
    return out


if __name__ == "__main__":
    import math
    import random
    # A sine sweep plus noise: enough to show drift if the tables are wrong.
    n = 40000
    src = [int(20000 * math.sin(i / (20 + i / 400.0)) + random.randint(-400, 400))
           for i in range(n)]
    src = [max(-32768, min(32767, s)) for s in src]
    raw = struct.pack(f"<{n}h", *src)
    enc = encode(raw)
    dec = decode(enc, n)
    err = sum(abs(a - b) for a, b in zip(src, dec)) / n
    peak = max(abs(a - b) for a, b in zip(src, dec))
    print(f"{len(raw)} bytes -> {len(enc)} ({len(enc) / len(raw):.2f}x), "
          f"mean error {err:.0f}, peak {peak}")

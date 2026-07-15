import math
import wave
import struct
import os

SAMPLE_RATE = 48000
VOLUME = 0.3

def generate_sine(freq, dur):
    total = int(SAMPLE_RATE * dur)
    return [math.sin(2 * math.pi * freq * (n / SAMPLE_RATE)) for n in range(total)]

def fade(samples, ms=5):
    fade_samples = int(SAMPLE_RATE * ms / 1000)
    total = len(samples)
    if fade_samples * 2 > total:
        return samples
    for i in range(fade_samples):
        g = i / fade_samples
        samples[i] *= g
        samples[total - 1 - i] *= g
    return samples

def silence(dur):
    return [0.0] * int(SAMPLE_RATE * dur)

def write_wav(samples, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not samples:
        raise ValueError("No samples to write for " + path)
    max_amp = max(abs(s) for s in samples) or 1.0
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        for s in samples:
            val = int((s / max_amp) * VOLUME * 32767)
            wf.writeframes(struct.pack("<h", val))
    print("Wrote", path, "samples:", len(samples))

def start_tone():
    gap = 0.04
    t1 = fade(generate_sine(740, 0.080))
    t2 = fade(generate_sine(880, 0.070))
    t3 = fade(generate_sine(1040, 0.090))
    return t1 + silence(gap) + t2 + silence(gap) + t3

def end_tone():
    def sweep(f0, f1, dur):
        total = int(SAMPLE_RATE * dur)
        samples = []
        for n in range(total):
            t = n / SAMPLE_RATE
            t_ratio = t / dur
            f = f0 + (f1 - f0) * t_ratio
            samples.append(math.sin(2 * math.pi * f * t))
        return samples
    t1 = fade(generate_sine(660, 0.090))
    t2 = fade(sweep(660, 520, 0.120))
    return t1 + t2

def alert_tone():
    gap = 0.060
    t1 = fade(generate_sine(1040, 0.120))
    t2 = fade(generate_sine(1040, 0.100))
    t3 = fade(generate_sine(1240, 0.150))
    return t1 + silence(gap) + t2 + silence(gap) + t3

if __name__ == "__main__":
    base = os.path.join(os.path.dirname(__file__), "assets", "sounds")
    write_wav(start_tone(), os.path.join(base, "aida_start.wav"))
    write_wav(end_tone(), os.path.join(base, "aida_end.wav"))
    write_wav(alert_tone(), os.path.join(base, "aida_alert.wav"))

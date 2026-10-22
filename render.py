#!/usr/bin/env python3
"""Render a faceless vertical video (1080x1920) with AI voice from a JSON spec.

Usage: python3 render.py specs/<slug>.json out/<slug>.mp4

Spec format:
{
  "kicker": "BACKEND / BUILD IN PUBLIC",
  "scenes": [
    {"voice": "Spoken sentence for this scene.",
     "lines": [{"t": "Big line", "accent": true}, {"t": "Smaller line", "size": 64}]},
    {"voice": "...", "code": "SELECT * FROM users\\nWHERE id = 1;", "lines": [{"t": "The query"}]}
  ]
}
Scene length follows the voice length. Needs ffmpeg, soundfile, kokoro-onnx.
"""
import json, os, subprocess, sys, textwrap, urllib.request

FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_M = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
BG, INK, ACC, MUT, CARD = "0x0E1512", "0xE4EDE8", "0x9AA5FF", "0x91A39A", "0x232A52"
FADE, VOICE = 0.4, "am_michael"
MODEL_DIR = os.environ.get("KOKORO_DIR", "/tmp/kokoro")
REL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        sys.exit("ffmpeg failed: " + r.stderr[-1500:])


def ensure_model():
    os.makedirs(MODEL_DIR, exist_ok=True)
    for f in ("kokoro-v1.0.onnx", "voices-v1.0.bin"):
        p = os.path.join(MODEL_DIR, f)
        if not os.path.exists(p) or os.path.getsize(p) < 1000000:
            print("downloading", f)
            urllib.request.urlretrieve(REL + f, p)


def ease(d, dur=0.5):
    return f"min(1,max(0,(t-{d})/{dur}))"


def main(spec_path, out_path):
    import soundfile as sf
    from kokoro_onnx import Kokoro

    spec = json.load(open(spec_path))
    scenes = spec["scenes"]
    kicker = spec.get("kicker", "BACKEND  /  BUILD IN PUBLIC")
    work = os.path.splitext(out_path)[0] + "_work"
    os.makedirs(work, exist_ok=True)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    ensure_model()
    k = Kokoro(os.path.join(MODEL_DIR, "kokoro-v1.0.onnx"), os.path.join(MODEL_DIR, "voices-v1.0.bin"))

    # 1. voice per scene, scene length from voice length
    lens, wavs = [], []
    for i, sc in enumerate(scenes):
        samples, sr = k.create(sc["voice"], voice=VOICE, speed=1.0, lang="en-us")
        d = len(samples) / sr
        p = f"{work}/v{i}.wav"
        sf.write(p, samples, sr)
        wavs.append(p)
        lens.append(max(3.4, d + 0.9))
        print(f"scene {i+1}: voice {d:.1f}s, scene {lens[-1]:.1f}s")

    # 2. render each scene
    clips = []
    for i, sc in enumerate(scenes):
        dur = lens[i]
        items = []  # (text, font, size, color, y)
        y = 560
        for j, ln in enumerate(sc.get("lines", [])):
            size = ln.get("size", 96 if j == 0 else 72)
            width = max(10, int(900 / (size * 0.62)))
            for part in textwrap.wrap(ln["t"], width=width) or [""]:
                items.append((part, FONT_B, size, ACC if ln.get("accent") else INK, y, len(items)))
                y += int(size * 1.35)
            y += 30
        if sc.get("code"):
            y += 40
            for cl in sc["code"].split("\n"):
                cl = cl[:34]
                items.append((cl, FONT_M, 44, INK, y, len(items), True))
                y += 62

        inputs = ["-f", "lavfi", "-i", f"color=c={BG}:s=1080x1920:r=30:d={dur}",
                  "-f", "lavfi", "-i", f"color=c={ACC}:s=1080x12:r=30:d={dur}"]
        fc = [f"[0:v]drawtext=fontfile={FONT_M}:text='{kicker}':fontcolor={ACC}:fontsize=34:x=(w-text_w)/2:y=260[v0]",
              f"[v0][1:v]overlay=x='-1080+1080*min(t/{dur},1)':y=1890[v1]"]
        cur = "v1"
        if sc.get("code"):
            n_code = len(sc["code"].split("\n"))
            top = y - 62 * n_code - 20
            inputs += ["-f", "lavfi", "-i", f"color=c={CARD}:s=960x{62*n_code+40}:r=30:d={dur}"]
            fc.append(f"[{cur}][2:v]overlay=x=60:y={top}[vc]")
            cur = "vc"
        for idx, it in enumerate(items):
            text, font, size, color, yy, order = it[:6]
            is_code = len(it) > 6
            d = 0.15 + 0.35 * order
            fn = f"{work}/t{i}_{idx}.txt"
            open(fn, "w").write(text)
            x = "110" if is_code else "(w-text_w)/2"
            fc.append(f"[{cur}]drawtext=fontfile={font}:textfile={fn}:fontcolor={color}:fontsize={size}:"
                      f"x={x}:y='{yy}+50*pow(1-{ease(d)},3)':alpha='{ease(d)}'[t{idx}]")
            cur = f"t{idx}"
        out = f"{work}/s{i}.mp4"
        run(["ffmpeg", "-y", "-loglevel", "error"] + inputs + ["-filter_complex", ";".join(fc), "-map", f"[{cur}]",
             "-t", str(dur), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", out])
        clips.append(out)

    # 3. join with slide transitions
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for c in clips:
        cmd += ["-i", c]
    fc, prev, acc = [], "0:v", 0.0
    for i in range(1, len(clips)):
        acc += lens[i - 1]
        off = round(acc - i * FADE, 2)
        fc.append(f"[{prev}][{i}:v]xfade=transition=slideleft:duration={FADE}:offset={off}[x{i}]")
        prev = f"x{i}"
    total = round(sum(lens) - (len(clips) - 1) * FADE, 2)

    # 4. mix the voice track
    starts, acc = [], 0.0
    for i in range(len(clips)):
        starts.append(round(acc - i * FADE + 0.25, 2))
        acc += lens[i]
    for i, p in enumerate(wavs):
        cmd += ["-i", p]
    base = len(clips)
    afc = []
    for i in range(len(wavs)):
        ms = int(starts[i] * 1000)
        afc.append(f"[{base+i}:a]aresample=44100,adelay={ms}|{ms}[a{i}]")
    afc.append("".join(f"[a{i}]" for i in range(len(wavs))) +
               f"amix=inputs={len(wavs)}:normalize=0,apad,atrim=0:{total},volume=1.2,alimiter=limit=0.85:level=disabled[mix]")
    run(cmd + ["-filter_complex", ";".join(fc + afc), "-map", f"[{prev}]", "-map", "[mix]",
               "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-t", str(total), out_path])
    print(f"done: {out_path} ({total}s)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])

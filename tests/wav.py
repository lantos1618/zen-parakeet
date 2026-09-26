#!/usr/bin/env python3
"""Exercise the Zen CLI's WAV reader with independent RIFF byte fixtures."""
from pathlib import Path
import os
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ZEN = ROOT.parent / "zen/zen"
with tempfile.TemporaryDirectory(prefix="zen-parakeet-wav-") as temporary:
    root = Path(temporary)
    (root / "wav.zen").write_text((ROOT / "src/wav.zen").read_text())
    (root / "main.zen").write_text('''Audio, decode = wav
main = (env: Env) Res<i32, AllocError> {
    a = env.mem.alloc();
    code ::= 1;
    env.fs.read(a, "input.wav").match({
        Ok(bytes) => decode(a, bytes.view()).match({
            Ok(audio) => { code = (audio.count == 2 && audio.rate == 16000 && audio.samples.read(0) == 0.5 && audio.samples.read(1) == -0.5).match({true => 0, false => 2}); },
            Err(_) => {},
        }),
        Err(_) => {},
    });
    Ok(code)
}
''')
    generated = root / "program.c"
    subprocess.run([str(ZEN), "build", str(root), "--emit-c", "-o", str(generated)],
                   env={**os.environ, "ZEN_STD": str(ROOT.parent / "zen/src")}, check=True)
    binary = root / "test"
    subprocess.run(["cc", "-std=c99", "-Wno-parentheses-equality", str(generated), "-o", str(binary)], check=True)
    def chunk(tag, data):
        return tag + struct.pack("<I", len(data)) + data + b"\0" * (len(data) % 2)
    def wave(body):
        return b"RIFF" + struct.pack("<I", len(body) + 4) + b"WAVE" + body
    fmt = chunk(b"fmt ", struct.pack("<HHIIHH", 3, 1, 16000, 64000, 4, 32))
    data = chunk(b"data", struct.pack("<2f", 0.5, -0.5))
    cases = [(wave(fmt + data), 0), (wave(chunk(b"JUNK", b"x") + fmt + data), 0),
             (b"RIFF", 1), (wave(fmt + b"data" + struct.pack("<I", 999)), 1),
             (wave(chunk(b"fmt ", b"x") + data), 1), (wave(fmt + chunk(b"data", b"")), 1),
             (wave(fmt + data + b"J"), 1)]
    for content, expected in cases:
        (root / "input.wav").write_bytes(content)
        result = subprocess.run([str(binary)], cwd=root)
        assert result.returncode == expected, result.returncode
print("7 WAV reader fixtures passed")

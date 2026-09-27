# Native Parakeet latency benchmark

All inference and timing happen in `main.zen` through the native `Recognizer`.
Python only prepares WAV bytes, builds/runs the executable, and summarizes its
output. This benchmark does not invoke a Python speech model or subprocess
transcription adapter.

Prerequisites are the verified SDK, model, and locally synthesized spoken WAV
described in the repository README. From the repository root:

```sh
python3 benchmarks/run.py --prepare-only
python3 benchmarks/run.py --skip-build --backend cpu
python3 benchmarks/run.py --skip-build --backend metal
```

Run backends sequentially without other benchmarks. Metal requires normal host
GPU access; a restrictive sandbox can fail to create a Metal command queue.
The runner does not close user apps, alter power settings, record a microphone,
or download dependencies. Hardware metadata uses only chip/core/memory fields,
not device serials or UUIDs.

The source phrase is repeated with 0.5 seconds of silence between copies and
trimmed to exact lengths of 1, 4, 8, and 15 seconds. The one-second clip cuts the
phrase early. This is synthesized-speech throughput testing, not a recognition
quality benchmark. A single local Q8 Parakeet model remains cached throughout
all lengths within each backend's process.

Each backend reports:

1. Model-open wall time in a fresh process. OS file caches are not flushed, so
   this is not a cold-disk measurement.
2. The first inference call on eight seconds of audio, before priming.
3. One excluded primer for each input length, then five measured warm calls.
4. Median and nearest-rank p95 warm latency, real-time factor, empty output
   counts, and the process maximum resident set size from `/usr/bin/time -l`.

Five samples make p95 equal to the observed maximum; this is a small-sample
baseline, not a tail-latency guarantee. The measurement covers the synchronous
Zen `transcribe` call, including native execution and copying the result. WAV
read/decode, printing, caller-arena teardown, UI rendering, actor messaging,
and audio capture are outside the measured interval. All fixtures are decoded
before model loading. Long-fixture sample storage remains live during the run
and contributes to the whole-process memory figure.

The clock is Darwin `clock_gettime(CLOCK_MONOTONIC)`; the benchmark-only binding
uses the SDK's numeric constant 6 and the 64-bit Darwin timespec layout. The
program rejects clock errors and emits six significant digits of timing data.
Generated C uses `-O2`; the prebuilt native SDK retains its release compiler
settings. Backend -1 selects CPU and backend 0 selects the first Metal device.

`build/benchmarks/` is ignored and contains metadata, fixture/model/library
hashes, exact flags and invocations, raw per-iteration logs, and summary JSON.
`RESULTS.md` records a measured snapshot and its limits. User apps and background
load remain uncontrolled; results are local observations, not general promises.

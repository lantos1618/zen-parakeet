# Native inference measurements — 2026-09-27 UTC

On this M2 Pro, warm native Parakeet transcription took 38–233 ms on Metal
and 78–620 ms on CPU for the tested 1–15 second inputs. These are local
synthesized-speech timing observations, not an ASR quality or latency guarantee.

## Warm timings

One cached recognizer per backend process, one excluded primer per duration,
then five timed calls. p95 is nearest-rank: with five samples it is simply the
observed maximum. Real-time factor is median wall time divided by audio duration.
Lower is faster. CPU ran first, followed by Metal, with other benchmark agents
paused. Existing user apps were left running; background load was uncontrolled.

| Backend | Audio | Median | p95 (max of 5) | Real-time factor | Empty outputs |
| --- | --- | --- | --- | --- | --- |
| Cpu | 1 s | 78.319 ms | 78.718 ms | 0.0783 | 0/5 |
| Cpu | 4 s | 244.167 ms | 267.685 ms | 0.0610 | 0/5 |
| Cpu | 8 s | 405.589 ms | 654.309 ms | 0.0507 | 0/5 |
| Cpu | 15 s | 619.680 ms | 685.145 ms | 0.0413 | 0/5 |
| Metal | 1 s | 38.324 ms | 39.679 ms | 0.0383 | 0/5 |
| Metal | 4 s | 83.213 ms | 97.796 ms | 0.0208 | 0/5 |
| Metal | 8 s | 144.436 ms | 147.619 ms | 0.0181 | 0/5 |
| Metal | 15 s | 233.275 ms | 234.993 ms | 0.0156 | 0/5 |

All measured warm outputs were nonempty. Captured examples included expected
phrase words; the one-second clip returned `the quick brown fox`. The first
8-second call returned three repetitions of the complete source phrase on both
backends. These checks detect broken/empty inference, not recognition accuracy.

## Startup and memory

| Measurement | CPU (-1) | Metal (0) |
| --- | --- | --- |
| Model-open wall time, one observation | 10014.100 ms | 82.970 ms |
| First inference, 8 seconds, before priming | 777.863 ms | 568.537 ms |
| Whole-process maximum RSS | 891,502,592 bytes (850.20 MiB) | 860,258,304 bytes (820.41 MiB) |

The CPU run's SDK log explicitly reports `ggml_metal_library_init: loaded in
9.901 sec`, before selecting its BLAS/CPU backend. This startup observation
includes GPU backend discovery/library initialization even though execution
used CPU. The following Metal process saw warmer OS/backend caches. Do not
interpret the model-open difference as an intrinsic CPU-versus-GPU loading
comparison. File/shader caches were not flushed and startup was sampled once.

Maximum RSS comes from `/usr/bin/time -l` for the complete process; it includes
all retained fixtures, model state, decoder and runtime memory. It is not an
isolated GPU-allocation metric, especially on this unified-memory machine.

## Configuration and scope

- Apple M2 Pro, 12 physical/logical CPU cores, 16 GiB RAM, arm64.
- macOS 26.6.2, build 25G83; Apple clang 17.0.0 (`clang-1700.6.4.2`).
- NeMo Speech v0.1.0 `macos-aarch64-metal`, prebuilt release SDK.
- NVIDIA Parakeet TDT 0.6B v3 Q8 model, 713,975,456 bytes; model repository
  revision `541d1f99c6b0c3cd0b11a95167540bb8edefd82b`.
- Zen compiler commit `44ad3b9d60be9409122d4216d8771ecae7adda87`; executable hash below
  identifies the actual built compiler, including any local working changes.
- C flags: `-O2 -std=c99 -Wno-parentheses-equality`, plus the installed SDK
  include directory and library rpath. The benchmark build graph links
  `nemo_speech_asr_c`; native SDK release optimization settings were unchanged.
- CPU uses SDK backend -1 (BLAS/CPU); Metal uses backend 0 (`MTL0`, Apple M2 Pro).
- Fixed model and native default decoder settings; one recognizer remains
  cached across every length. No parallel recognition jobs.
- Mono float32 at 16 kHz. The known Samantha-synthesized phrase is repeated
  with 0.5 s silence, then truncated to exact 1, 4, 8, or 15 second inputs.
- Fixtures decode before model loading. Only the synchronous Zen `transcribe`
  call is timed; native execution and transcript copying are included. WAV
  loading, UI, capture, actor messaging, printing and caller-arena teardown
  are excluded. Thus this is not end-to-end app dictation latency.
- Darwin monotonic clock and timespec size/field offsets checked against the
  installed SDK during the build. Timings print six significant digits.

## Raw warm samples

Milliseconds, in execution order:

| Backend | Audio | Five measured calls |
| --- | --- | --- |
| Cpu | 1 s | 78.718, 78.635, 78.319, 78.163, 77.726 |
| Cpu | 4 s | 267.685, 247.302, 244.167, 240.454, 240.361 |
| Cpu | 8 s | 430.363, 405.310, 400.089, 654.309, 405.589 |
| Cpu | 15 s | 685.145, 636.896, 619.680, 611.936, 615.284 |
| Metal | 1 s | 38.324, 39.679, 37.985, 39.515, 38.098 |
| Metal | 4 s | 78.372, 80.288, 97.796, 84.746, 83.213 |
| Metal | 8 s | 144.436, 147.405, 147.619, 140.495, 140.704 |
| Metal | 15 s | 233.275, 232.092, 234.993, 233.671, 231.986 |

## Identity and reproduction

See [README.md](README.md) for the benchmark commands and repository README
for explicit verified SDK/model installation. No dependencies are downloaded
by the benchmark. Preparation timestamp: `2026-09-27T05:07:22Z`.
Raw logs, JSON metadata, and generated fixtures are ignored under
`build/benchmarks/`; this document preserves the measured summary and samples.

| Artifact | SHA-256 |
| --- | --- |
| Zen compiler | `5688b03fceaf54fa1a9cb675c25260e1402c47247e9996ba7c51122aa676a285` |
| Benchmark Zen source | `b74d57f505c598635af57c8eb8a89b9fc9732db9f947c43f0ebda48ae2d630fc` |
| Native adapter Zen source | `7d3d7054f37c41fc090aa40377a44c65b2316bd554fd1772abb3cd838b631ab3` |
| WAV decoder Zen source | `e19abff851597c768252d871f7aa338176e0b0a4a3348e38a1a5f94c47792139` |
| Benchmark executable | `b36290073a93e910521fa42e7399433faede534a6159acddc3c42a041ddad3f2` |
| SDK release archive | `f1dff4f9dd9c96214f8cb78b982812459132df8a4ad1a42409fd94de4a366244` |
| SDK native dylib | `daf79cec8af12abf94d207236d9fb1558947396568d9be2691419cc04ef9d0bf` |
| SDK ASR header | `61057814efd3da0a25282e1f4b83719e938f5debe9ec29d442e1cf90cdd7d50e` |
| Parakeet Q8 model | `e3880d0aaaaf2c308ea2c35016b2b895c423eb3fda924c1b463d1c19b7f4d32e` |
| Source speech fixture | `d8c8d272aacd05c4c4dd034ff3c6546c9937b4d0d47dc8aea13a6e06bfb86a37` |
| 1 s input | `22b4fe784a25a8eb64306c9c3420e8e8346480ceaa5082b015ae9f348c666936` |
| 4 s input | `a5f96241037d2f0a15ad41d8bcc7dc330984275a839e87f61827ef2da443739d` |
| 8 s input | `402f5611dc5e8ff4e18581ff1d7008abc585ec4fbf44e3fbfb49f12f63e5563a` |
| 15 s input | `bd1f4cc2398f789e30662fba2277efc45ba8584cd42d95d4623e8ce791ca4f5a` |

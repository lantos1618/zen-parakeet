# zen-parakeet

Zen bindings and ownership for the NVIDIA NeMo Speech native ASR SDK. The
recognizer consumes borrowed mono float32 samples directly in process. There
is no Python, subprocess, or Objective-C bridge in this library.

NVIDIA's Parakeet TDT 0.6B v3 is the selected speech model. This SDK takes its
compatible local GGUF conversion, not the original NeMo checkpoint directory.
Supply the exact local model path explicitly; the library does not download or
substitute models. The native SDK remains an external C++ inference engine.

```zen
Recognizer, Error = parakeet
recognizer ::= Recognizer.open(a, model_path, -1).try(); // CPU; GPU index >= 0
@scope.defer(() { recognizer.close(); });
text = recognizer.transcribe(a, samples, count, 16000).try();
```

`transcribe` returns an owned `String` in the caller allocator. It accepts
mono `Ptr<f32>` samples at 8–96 kHz. The caller keeps sample storage alive until
the call completes. Calls are synchronous; inference belongs off the render
and capture threads. Recognition returns an empty string when the SDK reports
no alternatives. Native failures carry `NativeError { code, message }`, copied
before cleanup so the message survives subsequent native calls.

The recognizer owns one native handle; do not copy an open owner. `close()` is
idempotent on that instance and must follow all outstanding calls. Each result
is destroyed after copying its transcript, including failure paths. Startup
strings/configuration are temporary because the SDK copies them at creation.

Register `src/parakeet.zen` with `b.lib`, link `nemo_speech_asr_c`, and supply the
SDK's `lib` search directory. The C compiler also needs the SDK's `include`
directory and the executable needs an appropriate runtime library search path.
With the local SDK under `build/nemo-speech`, build the standalone smoke entry:

```sh
ZEN_STD=../zen/src \
CFLAGS="-I$PWD/build/nemo-speech/include -Wl,-rpath,$PWD/build/nemo-speech/lib" \
../zen/zen build .
./build/parakeet-smoke /absolute/path/to/parakeet-model.gguf /absolute/path/to/audio.wav
# Add --gpu to select GPU 0.
```

The smoke entry decodes mono IEEE float32 WAV (8–96 kHz) in Zen, then passes
aligned samples to the native model. It uses CPU unless `--gpu` is supplied.
GPU behavior depends on the installed native SDK backend and device support.
A locally synthesized phrase, "The quick brown fox jumps over the lazy dog,"
was transcribed correctly with the verified Parakeet v3 Q8 model on CPU and Metal. This
is a functional integration check, not an accuracy benchmark.

Run `python3 tests/native.py` to compile ABI checks against the installed header
and exercise success/failure cleanup with a native fixture. Checks cover the
size, alignment, and every field offset of pointer-passed configuration
records. These tests do not replace a real model inference run. The current
compiler lacks const-qualified pointers, so read-only native C strings are
represented as `Ptr<c_char>`; the adapter never writes to them. The fixture
suppresses only the associated qualifier warning while retaining incompatible
pointer checks. Header record changes require rerunning the ABI checks before
shipping with another SDK version.

Native contract: [NVIDIA SDK guide](https://github.com/NVIDIA/NeMo-Speech.cpp/blob/main/docs/sdk.md)
and [ASR header](https://github.com/NVIDIA/NeMo-Speech.cpp/blob/main/include/nemo_speech/asr.h).

## Reproduce the validated macOS arm64 setup

The integration used NVIDIA NeMo Speech **v0.1.0**, macOS arm64 Metal build,
and the model artifact pinned by that release's `model-index.json`:

| Artifact | SHA-256 |
| --- | --- |
| `nemo-speech-0.1.0-macos-aarch64-metal.tar.gz` | `f1dff4f9dd9c96214f8cb78b982812459132df8a4ad1a42409fd94de4a366244` |
| `parakeet-tdt-0.6b-v3.q8_0.gguf` (713,975,456 bytes) | `e3880d0aaaaf2c308ea2c35016b2b895c423eb3fda924c1b463d1c19b7f4d32e` |

The model repository is `nvidia/parakeet-tdt-0.6b-v3`, revision
`541d1f99c6b0c3cd0b11a95167540bb8edefd82b`. The release index records its
license as CC-BY-4.0; retain the model's attribution and license when packaging.

Run these explicit installation commands from this repository if needed:

```sh
mkdir -p build models
curl -fL 'https://github.com/NVIDIA/NeMo-Speech.cpp/releases/download/v0.1.0/nemo-speech-0.1.0-macos-aarch64-metal.tar.gz' -o build/nemo-speech-sdk.tar.gz
printf '%s\n' 'f1dff4f9dd9c96214f8cb78b982812459132df8a4ad1a42409fd94de4a366244  build/nemo-speech-sdk.tar.gz' | shasum -a 256 -c - && tar -xzf build/nemo-speech-sdk.tar.gz -C build
curl -fL 'https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3/resolve/541d1f99c6b0c3cd0b11a95167540bb8edefd82b/parakeet-tdt-0.6b-v3.q8_0.gguf' -o models/parakeet-tdt-0.6b-v3.q8_0.gguf
printf '%s\n' 'e3880d0aaaaf2c308ea2c35016b2b895c423eb3fda924c1b463d1c19b7f4d32e  models/parakeet-tdt-0.6b-v3.q8_0.gguf' | shasum -a 256 -c -
```

Neither build nor library code runs these downloads automatically. SDK binaries,
models, generated audio, and logs are ignored by Git.

After building as above, generate a known local fixture without recording a mic:

```sh
/usr/bin/say -v Samantha -o build/fixture.aiff 'The quick brown fox jumps over the lazy dog.'
/usr/bin/afconvert -f WAVE -d LEF32@16000 -c 1 build/fixture.aiff build/fixture.wav
./build/parakeet-smoke models/parakeet-tdt-0.6b-v3.q8_0.gguf build/fixture.wav
./build/parakeet-smoke models/parakeet-tdt-0.6b-v3.q8_0.gguf build/fixture.wav --gpu
```

Both CPU and Metal runs returned `the quick brown fox jumps over the lazy dog`
with exit status 0 on the development Mac. macOS speech synthesis and Metal
required normal host access outside the execution sandbox; sandboxed speech
produced empty audio and sandboxed Metal could not create a command queue.
`python3 tests/wav.py` additionally checks seven independent RIFF fixtures,
including malformed sizes and odd-sized chunk padding.

## Live dictation

The pinned Parakeet TDT v3 model has an offline encoder. Although the NeMo C
header exposes `StreamingRecognize`, attempting it with this model returns
`this transducer encoder is offline-only and cannot serve StreamingRecognize`.
An installed API does not imply every model supports it.

For live partial text, zen-tui periodically calls `Recognizer.transcribe` on
the growing recording, retains the recognizer on its inference actor, and
replaces the partial hypothesis as more context arrives. It admits only one
inference at a time and runs a final pass after capture stops. This is repeated
full-context decoding within a bounded recording, not cached incremental model
execution. Partial words can change and latency depends on hardware and audio
length. A cache-aware streaming model would require a separate stream adapter.

## Performance baseline

[Benchmark instructions](benchmarks/README.md) and
[measured results](benchmarks/RESULTS.md) separate process startup, first decode,
and warm CPU/Metal inference. These are timings on synthesized fixtures, not
a speech-recognition accuracy benchmark or end-to-end dictation latency.

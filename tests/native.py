#!/usr/bin/env python3
"""Validate the ABI against installed NVIDIA headers and exercise ownership."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--zen", type=Path, default=ROOT.parent / "zen/zen")
parser.add_argument("--sdk", type=Path, default=ROOT / "build/nemo-speech")
args = parser.parse_args()
header = args.sdk.resolve() / "include/nemo_speech/asr.h"
if not header.exists():
    raise SystemExit("Install the NVIDIA native SDK first; missing " + str(header))

with tempfile.TemporaryDirectory(prefix="zen-parakeet-abi-") as temporary:
    root = Path(temporary)
    (root / "parakeet.zen").write_text((ROOT / "src/parakeet.zen").read_text())
    (root / "main.zen").write_text((ROOT / "tests/main.zen").read_text())
    generated = root / "program.c"
    subprocess.run([str(args.zen.resolve()), "build", str(root), "--emit-c", "-o", str(generated)],
                   env={**os.environ, "ZEN_STD": str(ROOT.parent / "zen/src")}, check=True)
    source = generated.read_text()
    checks = ["\n#include <stddef.h>\n#include <assert.h>\n"]
    for zen, native in (("Backend", "backend_config"), ("Model", "model_config"),
                        ("Startup", "recognizer_config"), ("Options", "recognition_options")):
        match = re.search(r"struct (zu_t" + zen + r"_[a-z0-9]+) \{(.*?)\n\};", source, re.S)
        assert match, zen
        typename, body = match.groups()
        native = "nemo_speech_asr_" + native
        checks.append(f'_Static_assert(sizeof({typename}) == sizeof({native}), "{zen} size");\n')
        checks.append(f'_Static_assert(_Alignof({typename}) == _Alignof({native}), "{zen} alignment");\n')
        for field in re.findall(r"\b(zu_m\d+([a-z_]+));", body):
            mangled, plain = field
            checks.append(f'_Static_assert(offsetof({typename}, {mangled}) == offsetof({native}, {plain}), "{zen}.{plain}");\n')
    checks.append(r'''
struct nemo_speech_asr_recognizer { int alive; };
struct nemo_speech_asr_result { int alive; };
static struct nemo_speech_asr_recognizer fixture_recognizer;
static struct nemo_speech_asr_result fixture_result;
static char transcript[64] = "native fixture transcript";
static int destroyed, result_destroyed;
static const char *fixture_mode(void) { const char *s = getenv("NEMO_FIXTURE_MODE"); return s ? s : "success"; }
nemo_speech_asr_status nemo_speech_asr_create(const nemo_speech_asr_recognizer_config *cfg, nemo_speech_asr_recognizer **out) {
    assert(cfg && cfg->size == sizeof(*cfg));
    assert(cfg->backend && cfg->backend->size == sizeof(*cfg->backend) && cfg->backend->gpu == -1);
    assert(cfg->model && cfg->model->size == sizeof(*cfg->model));
    assert(strcmp(cfg->model->path, "model.gguf") == 0 && !cfg->model->name);
    assert(!cfg->streaming && !cfg->decoder && !cfg->vad && !cfg->endpointing && !cfg->postproc && !cfg->diar && !cfg->batching);
    fixture_recognizer.alive = 1; *out = &fixture_recognizer;
    return strcmp(fixture_mode(), "create-fail") == 0 ? NEMO_SPEECH_ASR_ERROR_RUNTIME : NEMO_SPEECH_ASR_OK;
}
void nemo_speech_asr_destroy(nemo_speech_asr_recognizer *r) { assert(r == &fixture_recognizer && r->alive); r->alive = 0; destroyed++; }
nemo_speech_asr_status nemo_speech_asr_recognize_f32(nemo_speech_asr_recognizer *r, const nemo_speech_asr_recognition_options *o, const float *samples, size_t n, int32_t rate, nemo_speech_asr_result **out) {
    assert(r->alive && o->size == sizeof(*o) && !o->request_id && !o->language_code);
    assert(!o->interim_results && !o->enable_word_time_offsets && !o->enable_automatic_punctuation && !o->verbatim_transcripts && !o->profanity_filter);
    assert(!o->stop_history_eou_ms && !o->speech_contexts && !o->speech_context_count && o->max_alternatives == 1 && !o->enable_speaker_diarization && !o->max_speaker_count);
    assert(n == 1 && rate == 16000 && samples[0] == 0.5f);
    fixture_result.alive = 1; *out = &fixture_result;
    return strcmp(fixture_mode(), "recognize-fail") == 0 ? NEMO_SPEECH_ASR_ERROR_RUNTIME : NEMO_SPEECH_ASR_OK;
}
size_t nemo_speech_asr_result_alternative_count(const nemo_speech_asr_result *r) { assert(r->alive); return 1; }
const char *nemo_speech_asr_result_transcript(const nemo_speech_asr_result *r, size_t alt) { assert(r->alive && alt == 0); return transcript; }
void nemo_speech_asr_result_destroy(nemo_speech_asr_result *r) { assert(r->alive); r->alive = 0; result_destroyed++; strcpy(transcript, "destroyed"); }
const char *nemo_speech_asr_last_error(void) { return "native fixture failure"; }
__attribute__((destructor)) static void check_cleanup(void) {
    assert(destroyed == 1);
    assert(result_destroyed == (strcmp(fixture_mode(), "create-fail") == 0 ? 0 : 1));
}
''')
    generated.write_text(source + "\n".join(checks))
    binary = root / "test"
    subprocess.run(["cc", "-std=c11", "-Werror=incompatible-pointer-types", "-Wno-incompatible-pointer-types-discards-qualifiers", "-Wno-parentheses-equality",
                    "-I" + str(header.parents[1]), str(generated), "-o", str(binary)], check=True)
    for mode, expected in (("success", 0), ("create-fail", 1), ("recognize-fail", 1)):
        result = subprocess.run([str(binary)], env={**os.environ, "NEMO_FIXTURE_MODE": mode}, capture_output=True, text=True)
        assert result.returncode == expected, (mode, result.returncode, result.stdout, result.stderr)
        if mode == "success":
            assert result.stdout.strip() == "native fixture transcript", result.stdout
print("Native header ABI sizes/alignments/offsets and 3 ownership cases passed")

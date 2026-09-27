#!/usr/bin/env python3
"""Build/run the Zen benchmark; Python creates WAV fixtures and summarizes only."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import shlex
import statistics
import struct
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--backend', choices=['cpu', 'metal', 'all'], default='all')
parser.add_argument('--prepare-only', action='store_true')
parser.add_argument('--skip-build', action='store_true')
parser.add_argument('--zen', type=Path, default=ROOT.parent / 'zen/zen')
parser.add_argument('--sdk', type=Path, default=ROOT / 'build/nemo-speech')
parser.add_argument('--model', type=Path, default=ROOT / 'models/parakeet-tdt-0.6b-v3.q8_0.gguf')
parser.add_argument('--fixture', type=Path, default=ROOT / 'build/fixture.wav')
args = parser.parse_args()
output = ROOT / 'build/benchmarks'
output.mkdir(parents=True, exist_ok=True)
sdk, model, fixture = args.sdk.resolve(), args.model.resolve(), args.fixture.resolve()
zen = args.zen.resolve()

def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()

def command(*values):
    result = subprocess.run(values, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else result.stderr.strip()

def chunk(tag, data):
    return tag + struct.pack('<I', len(data)) + data + b'\0' * (len(data) % 2)

def prepare():
    raw = fixture.read_bytes()
    if raw[:4] != b'RIFF' or raw[8:12] != b'WAVE':
        raise ValueError('Expected a RIFF/WAVE fixture')
    chunks, at = {}, 12
    while at + 8 <= len(raw):
        tag, size = struct.unpack_from('<4sI', raw, at)
        chunks[tag] = raw[at + 8:at + 8 + size]
        at += 8 + size + size % 2
    fmt = struct.unpack_from('<HHIIHH', chunks[b'fmt '])
    if fmt != (3, 1, 16000, 64000, 4, 32) or not chunks.get(b'data'):
        raise ValueError('Expected nonempty 16 kHz mono IEEE-float32 source')
    source = chunks[b'data']
    cycle = source + bytes(8000 * 4)  # Known phrase followed by 0.5 s silence.
    fixtures = []
    for seconds in (1, 4, 8, 15):
        length = seconds * 16000 * 4
        samples = (cycle * (length // len(cycle) + 1))[:length]
        body = b'WAVE' + chunk(b'fmt ', struct.pack('<HHIIHHH', 3, 1, 16000, 64000, 4, 32, 0))
        body += chunk(b'fact', struct.pack('<I', seconds * 16000)) + chunk(b'data', samples)
        path = output / f'speech-{seconds}s.wav'
        path.write_bytes(b'RIFF' + struct.pack('<I', len(body)) + body)
        fixtures.append({'seconds': seconds, 'path': str(path), 'sha256': digest(path)})
    return fixtures

flags = ['-O2', '-std=c99', '-Wno-parentheses-equality', '-I' + str(sdk / 'include'), '-Wl,-rpath,' + str(sdk / 'lib')]
if not args.skip_build:
    fixtures = prepare()
    project = output / 'project'
    project.mkdir(exist_ok=True)
    (project / 'main.zen').write_text((ROOT / 'benchmarks/main.zen').read_text())
    (project / 'build.zen').write_text('Builder, BuildError = std.build\nbuild = (b :: Builder) Res<(), BuildError> {\n'
        + 'parakeet = b.lib("parakeet", {src: Path(' + json.dumps(str(ROOT / 'src/parakeet.zen'))
        + '), libs: ["nemo_speech_asr_c"], paths: [' + json.dumps(str(sdk / 'lib')) + ']}).try();\n'
        + 'b.exe("benchmark", {src: Path("main.zen"), deps: [parakeet], out: Ok(Path("../benchmark"))}).try();\nOk(())\n}\n')
    env = {k: v for k, v in os.environ.items() if k not in ('CFLAGS', 'CC', 'ZEN_BUILD_OUTPUT', 'ZEN_BUILD_DIR', 'ZEN_SYMBOL_MAP')}
    env['ZEN_STD'] = str(ROOT.parent / 'zen/src')
    env['CFLAGS'] = shlex.join(flags)
    with (output / 'build.log').open('w') as log:
        subprocess.run([str(zen), 'build', str(project)], env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=180)
    generated = project / 'build/.zen/benchmark/program.c'
    clock_type = re.search(r'struct (zu_tTimespec_[a-z0-9]+) \{', generated.read_text()).group(1)
    abi = output / 'clock-abi.c'
    abi.write_text('#include <stddef.h>\n#include ' + json.dumps(str(generated)) + '\n'
                   + '_Static_assert(CLOCK_MONOTONIC == 6, "Darwin clock ID");\n'
                   + f'_Static_assert(sizeof({clock_type}) == sizeof(struct timespec), "timespec size");\n'
                   + f'_Static_assert(offsetof({clock_type}, zu_m7seconds) == offsetof(struct timespec, tv_sec), "seconds offset");\n'
                   + f'_Static_assert(offsetof({clock_type}, zu_m11nanoseconds) == offsetof(struct timespec, tv_nsec), "nanoseconds offset");\n')
    with (output / 'clock-abi.log').open('w') as log:
        subprocess.run(['/usr/bin/cc', '-std=c11', '-Wno-parentheses-equality', '-I' + str(sdk / 'include'),
                        '-fsyntax-only', str(abi)], stdout=log, stderr=subprocess.STDOUT, check=True, timeout=30)
    metadata = {
        'prepared_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'machine': {key: command('/usr/sbin/sysctl', '-n', key) for key in
                    ('machdep.cpu.brand_string', 'hw.memsize', 'hw.ncpu', 'hw.physicalcpu', 'hw.logicalcpu')},
        'os': command('/usr/bin/sw_vers'), 'architecture': platform.machine(),
        'compiler': command('/usr/bin/cc', '--version'), 'cflags': flags,
        'zen_sha256': digest(zen), 'zen_commit': command('git', '-C', str(ROOT.parent / 'zen'), 'rev-parse', 'HEAD'),
        'benchmark_source_sha256': digest(ROOT / 'benchmarks/main.zen'),
        'adapter_source_sha256': digest(ROOT / 'src/parakeet.zen'),
        'decoder_source_sha256': digest(ROOT / 'src/wav.zen'),
        'benchmark_binary_sha256': digest(output / 'benchmark'),
        'model': {'path': str(model), 'sha256': digest(model), 'bytes': model.stat().st_size},
        'sdk': {'path': str(sdk), 'header_sha256': digest(sdk / 'include/nemo_speech/asr.h'),
                'library_sha256': digest(sdk / 'lib/libnemo_speech_asr_c.dylib')},
        'source_fixture': {'path': str(fixture), 'sha256': digest(fixture),
                           'description': 'macOS Samantha synthesized The quick brown fox jumps over the lazy dog; repeated with 0.5s silence, truncated to exact duration'},
        'fixtures': fixtures, 'background_load': 'Uncontrolled; existing user apps left running, benchmark agents serialized.'
    }
    (output / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
else:
    metadata = json.loads((output / 'metadata.json').read_text())
    fixtures = metadata['fixtures']
# Refresh these when execution has ordinary host access (sandbox sysctl may fail).
for key in metadata['machine']:
    value = command('/usr/sbin/sysctl', '-n', key)
    if value and not value.startswith('sysctl:'):
        metadata['machine'][key] = value
archive = ROOT / 'build/research/nemo-speech-0.1.0-macos-aarch64-metal.tar.gz'
if archive.exists():
    metadata['sdk']['release'] = 'v0.1.0 macos-aarch64-metal'
    metadata['sdk']['archive_sha256'] = digest(archive)
(output / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
if args.prepare_only:
    print('Prepared:', output)
    raise SystemExit(0)

summary_path = output / 'summary.json'
summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
for backend in (('cpu', 'metal') if args.backend == 'all' else (args.backend,)):
    invocation = ['/usr/bin/time', '-l', str(output / 'benchmark'), str(model), backend] + [row['path'] for row in fixtures]
    log_path = output / f'{backend}.log'
    started = time.monotonic()
    with log_path.open('w') as log:
        result = subprocess.run(invocation, stdout=log, stderr=subprocess.STDOUT, timeout=900)
    elapsed = time.monotonic() - started
    lines = log_path.read_text().splitlines()
    if result.returncode:
        raise SystemExit(f'{backend} failed ({result.returncode}); see {log_path}')
    samples, texts, load = [], [], None
    for line in lines:
        fields = line.split('\t')
        if fields[0] == 'LOAD':
            load = float(fields[2])
        elif fields[0] == 'SAMPLE':
            samples.append({'phase': fields[1], 'seconds': int(fields[2]), 'iteration': int(fields[3]),
                            'milliseconds': float(fields[4]), 'text_bytes': int(fields[5])})
        elif fields[0] == 'TEXT':
            texts.append({'phase': fields[1], 'seconds': int(fields[2]), 'text': '\t'.join(fields[3:])})
    if load is None or load < 0 or len(samples) != 25:
        raise SystemExit(f'Incomplete timings for {backend}: {len(samples)} rows')
    warm = []
    for seconds in (1, 4, 8, 15):
        group = [row for row in samples if row['phase'] == 'warm' and row['seconds'] == seconds]
        if len(group) != 5 or any(row['milliseconds'] < 0 for row in group):
            raise SystemExit('Missing/invalid warm measurements')
        if seconds > 1 and any(row['text_bytes'] == 0 for row in group):
            raise SystemExit(f'Unexpected empty transcript: {backend} {seconds}s')
        for row in [r for r in texts if r['seconds'] == seconds]:
            if seconds > 1 and not any(word in row['text'].lower() for word in ('quick', 'brown', 'fox')):
                raise SystemExit(f'Expected phrase words missing: {row}')
        times = sorted(row['milliseconds'] for row in group)
        median = statistics.median(times)
        warm.append({'seconds': seconds, 'iterations': 5, 'median_ms': median,
                     'p95_ms_nearest_rank': times[math.ceil(0.95 * len(times)) - 1],
                     'real_time_factor': median / (seconds * 1000),
                     'empty_outputs': sum(row['text_bytes'] == 0 for row in group)})
    rss = re.search(r'^\s*(\d+)\s+maximum resident set size\s*$', '\n'.join(lines), re.M)
    summary[backend] = {'command': invocation, 'process_seconds': elapsed, 'model_load_ms': load,
                        'first_call': next(row for row in samples if row['phase'] == 'first'),
                        'warm': warm, 'peak_rss_bytes': int(rss.group(1)) if rss else None,
                        'samples': samples, 'texts': texts, 'log': str(log_path)}
    summary_path.write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({backend: {k:v for k,v in summary[backend].items() if k not in ('samples','texts','command')}}, indent=2), flush=True)

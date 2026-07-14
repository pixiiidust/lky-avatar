# assets/voices

Elder-LKY voice reference material goes here at runtime:

- 6–12 s single-speaker reference clips (e.g. `elder/*.wav`)
- rights metadata: source, date, processing steps, permission notes
  (`elder/metadata.json`)

**Tooling:** produce clips + metadata with
`python scripts/prepare_voice_reference.py <source> --start MM:SS --end MM:SS ...`
(needs ffmpeg; it prints install steps if missing). Then follow
[`docs/voice-blind-test.md`](../../docs/voice-blind-test.md) — the blind-test
working tree also lives here, under `blind-test/`.

**Never committed.** This directory's contents are gitignored — a real
person's voice references and their rights metadata stay local-only (plan §9).
Only this README and `.gitkeep` are tracked.

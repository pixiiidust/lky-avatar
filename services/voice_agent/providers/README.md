# providers

Swappable speech-provider adapters behind the livekit-agents plugin
interfaces, so engines exchange without touching the agent.

- `tts.py` — `ChatterboxTTS` (issue #8): the cloned elder voice, a
  non-streaming `tts.TTS` implementation that POSTs each phrase to the
  loopback-only `services/tts_server`. The SDK's `StreamAdapter` supplies
  sentence segmentation, synthesis-ahead-of-playback, and atomic
  cancellation on barge-in (see the module docstring for the verified
  mechanism). Provider selection lives in `agent.build_tts` /
  `config.select_tts_provider` (`TTS_PROVIDER` env: `deepgram` default,
  `chatterbox` for the cloned voice).
- STT remains the stock Deepgram plugin (configured directly in
  `agent.py`); a custom adapter would earn its place here only if the STT
  provider ever needs swapping.

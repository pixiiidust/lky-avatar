"""LiveKit TTS adapter for the self-hosted cloned-voice server (issue #8).

``ChatterboxTTS`` implements the livekit-agents ``tts.TTS`` interface as a
NON-streaming provider (``TTSCapabilities(streaming=False)``): each
``synthesize(text)`` is one HTTP POST to the loopback TTS server
(services/tts_server, WSL) which returns raw 24 kHz mono PCM.

Phrase streaming and interruption come from the SDK, not from this file —
verified against livekit-agents 1.6.5 source:

- ``Agent.default.tts_node`` (voice/agent.py) sees ``streaming=False`` and
  wraps this TTS in ``tts.StreamAdapter`` with the blingfire
  ``SentenceTokenizer``: LLM output is segmented into sentences, and each
  sentence becomes one ``synthesize()`` call, pipelined ahead of playback
  (``StreamAdapterWrapper._synthesize`` synthesizes the next sentence while
  earlier audio is still playing out). This is exactly the mechanism the
  stock Deepgram plugin's queue rides on.
- On barge-in the session cancels the ``tts_node`` generator; the
  ``async with wrapped_tts.stream(...)`` exits, ``StreamAdapterWrapper``
  cancels its tokenizer+synthesis tasks, which closes the in-flight
  ``ChunkedStream`` here (aborting the HTTP request) and drops every queued
  sentence — one atomic cancellation, identical to the Deepgram path.

Failure behavior: errors are raised as the SDK's ``APIError`` family, so a
dead/timing-out TTS server flows into the session's existing error handling
(``AgentSession._on_error`` tolerates ``max_unrecoverable_errors`` TTS
failures before closing; each failed turn is logged and the conversation —
including the streamed transcript — continues). Flipping ``TTS_PROVIDER``
back to ``deepgram`` is the operator-level fallback.

The pronunciation map is applied here, per phrase, just before the request:
the SDK emits the visitor-facing transcript from the ORIGINAL sentence
before calling ``synthesize()``, so only the engine sees the respellings.
"""

from __future__ import annotations

import asyncio

import aiohttp

from livekit.agents import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    tts,
    utils,
)
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions

from pronunciation import PronunciationMap

DEFAULT_BASE_URL = "http://127.0.0.1:8100"
#: The server synthesizes at Chatterbox's native rate; the adapter pins it
#: and refuses mismatched audio rather than garbling playback.
SAMPLE_RATE = 24_000
NUM_CHANNELS = 1

#: Per-request ceiling. Phrases are single sentences (measured: ~1.3-3.3s
#: wall for typical sentences at RTF ~0.4), but the ceiling must also cover
#: a cold CUDA graph on the first request after server start.
REQUEST_TIMEOUT_SECONDS = 60.0


class ChatterboxTTS(tts.TTS):
    """The cloned LKY voice, via the loopback-only tts_server seam."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        speed: float | None = None,
        pronunciations: PronunciationMap | None = None,
        http_session: aiohttp.ClientSession | None = None,
    ) -> None:
        """
        Args:
            base_url: the tts_server root (never a public host; spec §9 —
                the agent is this endpoint's only client).
            speed: delivery-speed factor sent with every request
                (LKY_TTS_SPEED; <1 slows the engine's too-fast elder voice
                toward the real 82-year-old's rate). None lets the server's
                own default apply.
            pronunciations: spelling->respelling rewriter applied to each
                phrase before synthesis (see pronunciation.py).
            http_session: injectable aiohttp session (tests use this; the
                agent process uses the SDK's shared session).
        """
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=SAMPLE_RATE,
            num_channels=NUM_CHANNELS,
        )
        self._base_url = base_url.rstrip("/")
        self._speed = speed
        self._pronunciations = pronunciations or PronunciationMap({})
        self._session = http_session

    @property
    def model(self) -> str:
        return "chatterbox"

    @property
    def provider(self) -> str:
        return "lky-tts-server"

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def speed(self) -> float | None:
        return self._speed

    def _ensure_session(self) -> aiohttp.ClientSession:
        if not self._session:
            self._session = utils.http_context.http_session()
        return self._session

    def synthesize(
        self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> ChunkedStream:
        return ChunkedStream(tts=self, input_text=text, conn_options=conn_options)


class ChunkedStream(tts.ChunkedStream):
    """One phrase -> one POST /synthesize -> raw PCM pushed as frames."""

    def __init__(
        self, *, tts: ChatterboxTTS, input_text: str, conn_options: APIConnectOptions
    ) -> None:
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._tts: ChatterboxTTS = tts

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        payload: dict[str, object] = {
            # Respellings go to the engine only — the SDK already emitted
            # the visitor-facing transcript from the original text.
            "text": self._tts._pronunciations.apply(self._input_text),
            "format": "pcm",
        }
        if self._tts._speed is not None:
            payload["speed"] = self._tts._speed

        try:
            async with self._tts._ensure_session().post(
                f"{self._tts._base_url}/synthesize",
                json=payload,
                timeout=aiohttp.ClientTimeout(
                    total=REQUEST_TIMEOUT_SECONDS,
                    sock_connect=self._conn_options.timeout,
                ),
            ) as resp:
                resp.raise_for_status()

                server_rate = int(
                    resp.headers.get("X-Sample-Rate", str(SAMPLE_RATE))
                )
                if server_rate != self._tts.sample_rate:
                    # Mis-rated PCM plays as garbage — fail the request
                    # instead. (Would only happen if the server's engine
                    # changed underneath the adapter.)
                    raise APIError(
                        f"TTS server returned sample rate {server_rate}, "
                        f"adapter expects {self._tts.sample_rate}"
                    )

                output_emitter.initialize(
                    request_id=utils.shortuuid(),
                    sample_rate=self._tts.sample_rate,
                    num_channels=NUM_CHANNELS,
                    mime_type="audio/pcm",
                )
                async for data, _ in resp.content.iter_chunks():
                    output_emitter.push(data)
                # no explicit flush: ChunkedStream._main_task's end_input()
                # flushes and tags the real last frame is_final (an explicit
                # flush here would append a synthetic silence marker instead)

        except asyncio.TimeoutError:
            raise APITimeoutError() from None
        except aiohttp.ClientResponseError as e:
            raise APIStatusError(
                message=e.message, status_code=e.status, request_id=None, body=None
            ) from None
        except APIError:
            raise
        except Exception as e:
            raise APIConnectionError() from e

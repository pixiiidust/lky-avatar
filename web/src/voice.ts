/**
 * Voice-outage slate (issue #13). If the cloned-voice TTS server dies
 * mid-session, the agent keeps the interview going in a degraded-but-honest
 * mode: it publishes `lky.tts = "error"` on its participant attributes and
 * delivers his replies as text-only transcript turns (no audio). The studio
 * must say so in its own voice — a slate card explaining that the sound is
 * down and the replies continue in print — and clear the slate when the
 * agent reports `"ok"` again (the next successful synthesis).
 *
 * Pure module: maps the last reported `lky.tts` status to a slate view or
 * null; no DOM, no LiveKit. Tested in voice.test.ts; main.ts wires it to
 * the ParticipantAttributesChanged event, exactly like `lky.brain`.
 */

export interface VoiceNotice {
  /** Slate caption (CSS sets it in letterspaced caps). */
  caption: string;
  /** One sentence of ink: the sound is down, the record continues. */
  message: string;
}

const VOICE_DOWN: VoiceNotice = {
  caption: "Sound is down",
  message:
    "His voice is unavailable for the moment — his replies continue " +
    "in print, on the record.",
};

/**
 * The designed notice for the reported TTS status, or null when the voice
 * is fine. Unknown values fail open (no slate): only an explicit "error"
 * may occupy the set.
 */
export function voiceNoticeFor(ttsStatus: string): VoiceNotice | null {
  return ttsStatus === "error" ? VOICE_DOWN : null;
}

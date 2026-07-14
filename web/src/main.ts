import {
  Room,
  RoomEvent,
  Track,
  type RemoteTrack,
  type RemoteTrackPublication,
  type TextStreamReader,
} from "livekit-client";
import { TranscriptStore, type Segment } from "./transcript.ts";
import {
  AvatarStateMachine,
  type AgentEvent,
  type AgentReportedState,
  type AvatarIntent,
} from "./avatar/stateMachine.ts";
import { lampView, type ConnectionPhase } from "./lamp.ts";
import { RmsLipSync } from "./avatar/lipSync.ts";
import { createAvatarView, type AvatarView } from "./avatar/Live2DAvatar.ts";
import "@fontsource-variable/literata/opsz.css";
import "@fontsource-variable/literata/opsz-italic.css";
import "@fontsource-variable/archivo";
import "@fontsource-variable/archivo/wght-italic.css";
import "./style.css";

const TOKEN_SERVER_URL: string =
  import.meta.env.VITE_TOKEN_SERVER_URL ?? "http://localhost:8090";

const TRANSCRIPTION_TOPIC = "lk.transcription";

/**
 * Typed questions travel to the agent on the SDK's text-input topic
 * (livekit-agents 1.6.5 `TOPIC_CHAT`): RoomIO's default text-input callback
 * interrupts the current speech and generates a spoken reply — the full
 * voice + record experience with no agent-side changes.
 */
const CHAT_TOPIC = "lk.chat";

/**
 * Participant attribute the agent publishes its brain status on (issue #6):
 * "ok" | "busy" (single-slot brain already answering someone) | "error"
 * (brain unreachable / failed).
 */
const BRAIN_ATTRIBUTE = "lky.brain";
const BRAIN_BUSY_TEXT = "LKY is speaking with someone — please wait.";
const BRAIN_ERROR_TEXT =
  "LKY's brain is unreachable right now — please try again shortly.";
const MIC_UNAVAILABLE_TEXT =
  "The microphone is unavailable, so pass him a written note below — " +
  "he will still answer aloud, on the record.";

/** Values LiveKit Agents publishes on the `lk.agent.state` attribute. */
const AGENT_STATES: ReadonlySet<string> = new Set([
  "initializing",
  "idle",
  "listening",
  "thinking",
  "speaking",
] satisfies AgentReportedState[]);

const connectBtn = document.querySelector<HTMLButtonElement>("#connect-btn")!;
const transcriptEl = document.querySelector<HTMLOListElement>("#transcript")!;
const audioSink = document.querySelector<HTMLDivElement>("#audio-sink")!;
const avatarStage = document.querySelector<HTMLDivElement>("#avatar-stage")!;
const demoPanel = document.querySelector<HTMLElement>("#demo-panel")!;
const lampEl = document.querySelector<HTMLDivElement>("#studio-lamp")!;
const lampCaptionEl = document.querySelector<HTMLSpanElement>("#lamp-caption-text")!;
const slateCardEl = document.querySelector<HTMLDivElement>("#slate-card")!;
const slateCaptionEl = document.querySelector<HTMLParagraphElement>("#slate-caption")!;
const slateMessageEl = document.querySelector<HTMLParagraphElement>("#slate-message")!;
const noteDetails = document.querySelector<HTMLDetailsElement>("#note-details")!;
const noteForm = document.querySelector<HTMLFormElement>("#note-form")!;
const noteInput = document.querySelector<HTMLInputElement>("#note-input")!;
const noteSend = document.querySelector<HTMLButtonElement>("#note-send")!;
const noteStatus = document.querySelector<HTMLParagraphElement>("#note-status")!;

const transcript = new TranscriptStore();
let room: Room | null = null;

// --- Presentation state (drives the lamp + slate card) ---------------------

let connection: ConnectionPhase = "disconnected";
/** State of the last applied avatar intent (the lamp follows this). */
let avatarState: AvatarIntent["state"] = "idle";
/** Last brain status reported by the agent ("ok" until told otherwise). */
let brainStatus = "ok";
/** Error message held by the avatar state machine (its error state). */
let machineMessage: string | null = null;
/** Mic-permission fallback notice (typed input surfaced instead). */
let micNotice: string | null = null;

// --- Avatar: state machine + renderer + played-audio lip sync -------------

const machine = new AvatarStateMachine();
const lipSync = new RmsLipSync();
let avatarView: AvatarView | null = null;
/** Whether the agent is currently audible (drives playback events). */
let agentAudible = false;

/** The studio lamp: single indicator for the whole state machine. */
function renderLamp(): void {
  const view = lampView({ connection, avatarState, brainStatus });
  lampEl.dataset.light = view.light;
  lampEl.dataset.live = view.live ? "1" : "0";
  lampCaptionEl.textContent = view.caption;
}

/** Slate card: busy / error / mic notices in the studio's voice. */
function renderSlate(): void {
  let caption: string | null = null;
  let message = "";
  let tone = "trouble";
  if (machineMessage !== null) {
    caption = "Off air";
    message = machineMessage;
  } else if (brainStatus === "busy") {
    caption = "In session";
    message = BRAIN_BUSY_TEXT;
  } else if (brainStatus === "error") {
    caption = "Off air";
    message = BRAIN_ERROR_TEXT;
  } else if (micNotice !== null) {
    caption = "Written questions";
    message = micNotice;
    tone = "quiet";
  }
  slateCardEl.hidden = caption === null;
  slateCardEl.dataset.tone = tone;
  slateCaptionEl.textContent = caption ?? "";
  slateMessageEl.textContent = message;
}

function updateAvatarDom(intent: AvatarIntent): void {
  avatarStage.dataset.avatarState = intent.state;
  avatarState = intent.state;
  machineMessage = intent.statusMessage;
  renderSlate();
  renderLamp();
}

function applyIntent(intent: AvatarIntent): void {
  avatarView?.applyIntent(intent);
  updateAvatarDom(intent);
}

/** Feed the avatar state machine and apply the resulting intent. */
function dispatchAvatarEvent(event: AgentEvent): void {
  applyIntent(machine.handle(event));
}

function applyBrainStatus(status: string): void {
  if (status === brainStatus) return;
  brainStatus = status;
  if (status === "error") {
    dispatchAvatarEvent({ type: "connection-error", message: BRAIN_ERROR_TEXT });
  }
  renderSlate();
  renderLamp();
}

function setConnection(phase: ConnectionPhase): void {
  connection = phase;
  renderLamp();
}

// --- The record -------------------------------------------------------------

function attributionFor(seg: Segment): string {
  if (seg.speaker === "lee") return "Lee";
  return seg.kind === "written" ? "You · written" : "You";
}

function renderTranscript(): void {
  let previousKey = "";
  transcriptEl.replaceChildren(
    ...transcript.list().map((seg) => {
      const li = document.createElement("li");
      li.classList.add(seg.final ? "final" : "interim");
      li.dataset.speaker = seg.speaker;
      li.dataset.kind = seg.kind;
      // Hansard-style: attribute a run of segments once, not every line.
      const key = `${seg.speaker}:${seg.kind}`;
      if (key === previousKey) li.classList.add("continues");
      previousKey = key;
      const who = document.createElement("span");
      who.className = "speaker";
      who.textContent = attributionFor(seg);
      const text = document.createElement("span");
      text.className = "text";
      text.textContent = seg.text;
      li.append(who, text);
      return li;
    }),
  );
  transcriptEl.scrollTop = transcriptEl.scrollHeight;
}

async function fetchToken(): Promise<{ token: string; url: string }> {
  const resp = await fetch(`${TOKEN_SERVER_URL}/api/token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  if (!resp.ok) {
    let detail = `token server responded ${resp.status}`;
    try {
      detail = (await resp.json()).detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return resp.json();
}

/** One text stream = one update for one transcription segment. */
async function handleTranscription(
  reader: TextStreamReader,
  participantInfo: { identity: string },
): Promise<void> {
  const segmentId = reader.info.attributes?.["lk.segment_id"] ?? reader.info.id;
  const isFinal = reader.info.attributes?.["lk.transcription_final"] === "true";
  const isLocal = participantInfo.identity === room?.localParticipant.identity;
  const speaker = isLocal ? "you" : "lee";

  transcript.beginSegment(segmentId, speaker);
  for await (const chunk of reader) {
    transcript.appendText(segmentId, chunk);
    renderTranscript();
  }
  if (isFinal) {
    transcript.markFinal(segmentId);
  }
  renderTranscript();
}

function handleTrackSubscribed(
  track: RemoteTrack,
  publication: RemoteTrackPublication,
): void {
  if (track.kind === Track.Kind.Audio) {
    const el = track.attach();
    el.dataset.trackSid = publication.trackSid;
    audioSink.append(el);
    // Lip sync analyses the SAME track the visitor hears (spec: mouth is
    // driven by the RMS of the played audio, never generation-side timing).
    lipSync.attachTrack(track.mediaStreamTrack);
  }
}

function handleTrackUnsubscribed(track: RemoteTrack): void {
  track.detach().forEach((el) => el.remove());
  if (track.kind === Track.Kind.Audio) {
    lipSync.detach();
    if (agentAudible) {
      agentAudible = false;
      dispatchAvatarEvent({ type: "playback-stopped" });
    }
  }
}

// --- Passing a note (typed input over lk.chat) ------------------------------

function setNoteStatus(text: string | null, tone: "quiet" | "trouble" = "quiet"): void {
  noteStatus.hidden = text === null;
  noteStatus.textContent = text ?? "";
  noteStatus.dataset.tone = tone;
}

/** Surface the note card (mic failed / permission denied). */
function offerNoteCard(): void {
  micNotice = MIC_UNAVAILABLE_TEXT;
  renderSlate();
  noteDetails.open = true;
  noteInput.focus();
}

async function passNote(text: string): Promise<void> {
  if (demoMode) {
    // Dev harness only: show the note resolving into the record.
    transcript.addNote("you", text);
    renderTranscript();
    return;
  }
  if (!room || connection !== "connected") {
    setNoteStatus("Begin the interview first — then pass your note.", "trouble");
    return;
  }
  noteSend.disabled = true;
  try {
    await room.localParticipant.sendText(text, { topic: CHAT_TOPIC });
    // The agent does not echo lk.chat input back on the transcription
    // topic, so the client sets the written question into the record.
    transcript.addNote("you", text);
    renderTranscript();
    noteInput.value = "";
    setNoteStatus(null);
  } catch (err) {
    console.error("failed to pass note", err);
    setNoteStatus("The note could not be passed — please try again.", "trouble");
  } finally {
    noteSend.disabled = false;
  }
}

noteForm.addEventListener("submit", (ev) => {
  ev.preventDefault();
  const text = noteInput.value.trim();
  if (text.length === 0) return;
  void passNote(text);
});

// --- Session ------------------------------------------------------------------

async function connect(): Promise<void> {
  connectBtn.disabled = true;
  setConnection("connecting");
  try {
    const { token, url } = await fetchToken();

    room = new Room();
    room
      .on(RoomEvent.TrackSubscribed, handleTrackSubscribed)
      .on(RoomEvent.TrackUnsubscribed, handleTrackUnsubscribed)
      .on(RoomEvent.Disconnected, onDisconnected)
      .on(RoomEvent.ParticipantAttributesChanged, (attrs, participant) => {
        if (participant.identity === room?.localParticipant.identity) {
          return;
        }
        // Brain status (issue #6): busy shows the IN SESSION slate; error
        // feeds the avatar state machine's error state (neutral pose +
        // OFF AIR slate). Both are sticky until the agent reports ok again.
        const brain = attrs[BRAIN_ATTRIBUTE];
        if (brain) {
          applyBrainStatus(brain);
        }
        // The agent publishes its state (listening/thinking/speaking); the
        // studio lamp is the single visible readout.
        const state = attrs["lk.agent.state"];
        if (state && AGENT_STATES.has(state)) {
          dispatchAvatarEvent({
            type: "agent-state",
            state: state as AgentReportedState,
          });
        }
      })
      .on(RoomEvent.ActiveSpeakersChanged, (speakers) => {
        // "Playback" for the state machine means: agent audio is audible
        // right now. (The WebRTC <audio> element plays continuously, so its
        // play/pause events cannot signal turn boundaries.)
        const audible = speakers.some(
          (p) => p.identity !== room?.localParticipant.identity,
        );
        if (audible !== agentAudible) {
          agentAudible = audible;
          dispatchAvatarEvent({
            type: audible ? "playback-started" : "playback-stopped",
          });
        }
      });
    room.registerTextStreamHandler(TRANSCRIPTION_TOPIC, (reader, info) => {
      handleTranscription(reader, info).catch((err) =>
        console.error("transcription stream error", err),
      );
    });

    await room.connect(url, token);

    transcript.clear();
    renderTranscript();
    brainStatus = "ok";
    micNotice = null;
    setConnection("connected");
    connectBtn.textContent = "End the interview";

    // The microphone is the primary path, but its failure must not end the
    // interview: the visitor can pass written notes over lk.chat instead
    // (no device, permission denied, noisy room — issue #33 addition).
    try {
      await room.localParticipant.setMicrophoneEnabled(true);
    } catch (err) {
      console.warn("microphone unavailable, offering written notes", err);
      offerNoteCard();
    }
    renderSlate();
  } catch (err) {
    console.error(err);
    dispatchAvatarEvent({
      type: "connection-error",
      message: `The interview could not begin: ${(err as Error).message}`,
    });
    await teardown();
    setConnection("disconnected");
    connectBtn.textContent = "Begin the interview";
  } finally {
    connectBtn.disabled = false;
  }
}

async function teardown(): Promise<void> {
  if (room) {
    room.unregisterTextStreamHandler(TRANSCRIPTION_TOPIC);
    await room.disconnect();
    room = null;
  }
  audioSink.replaceChildren();
}

function onDisconnected(): void {
  connectBtn.textContent = "Begin the interview";
  audioSink.replaceChildren();
  room = null;
  lipSync.detach();
  agentAudible = false;
  brainStatus = "ok";
  micNotice = null;
  setConnection("disconnected");
  // The machine keeps a visible error state through disconnect; a clean
  // disconnect returns the avatar to idle.
  dispatchAvatarEvent({ type: "disconnected" });
}

connectBtn.addEventListener("click", () => {
  if (room) {
    void teardown();
  } else {
    void connect();
  }
});

// --- Startup: mount the avatar; enter demo mode with ?avatarDemo=1 --------

const demoMode = new URLSearchParams(location.search).get("avatarDemo") === "1";

void (async () => {
  avatarView = await createAvatarView(avatarStage, { lipSync });
  applyIntent(machine.intent);

  if (demoMode) {
    // Keyless demo: fake agent events + generated audio, no LiveKit.
    connectBtn.disabled = true;
    connection = "connected"; // let the lamp show the machine's states
    renderLamp();
    const { startAvatarDemo } = await import("./avatar/demo.ts");
    startAvatarDemo({
      view: avatarView,
      lipSync,
      panel: demoPanel,
      audioSink,
      onIntent: updateAvatarDom,
      studio: {
        setBrainStatus: applyBrainStatus,
        seedRecord: () => {
          transcript.clear();
          transcript.beginSegment("d1", "you");
          transcript.appendText(
            "d1",
            "Minister, Singapore spends heavily on AI now. If the bet is wrong, what then?",
          );
          transcript.markFinal("d1");
          transcript.beginSegment("d2", "lee");
          transcript.appendText(
            "d2",
            "Then we will have trained a generation of engineers and lost some money. " +
              "If the bet is right and we had not made it, we would have lost the future. " +
              "That is not a difficult sum.",
          );
          transcript.markFinal("d2");
          transcript.beginSegment("d3", "lee");
          transcript.appendText(
            "d3",
            "The point is not the machine. The point is whether your people can use it " +
              "before your competitors do.",
          );
          transcript.markFinal("d3");
          transcript.addNote("you", "And if the talent leaves for better pay abroad?");
          transcript.beginSegment("d4", "lee");
          transcript.appendText(
            "d4",
            "Some will go. Your job is to make staying the intelligent choice, not the loyal one…",
          );
          renderTranscript();
        },
        offerNoteCard,
      },
    });
  }
})();

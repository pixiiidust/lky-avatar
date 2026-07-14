import {
  Room,
  RoomEvent,
  Track,
  type RemoteTrack,
  type RemoteTrackPublication,
  type TextStreamReader,
} from "livekit-client";
import { TranscriptStore } from "./transcript.ts";
import "./style.css";

const TOKEN_SERVER_URL: string =
  import.meta.env.VITE_TOKEN_SERVER_URL ?? "http://localhost:8090";

const TRANSCRIPTION_TOPIC = "lk.transcription";

const connectBtn = document.querySelector<HTMLButtonElement>("#connect-btn")!;
const statusEl = document.querySelector<HTMLSpanElement>("#status")!;
const transcriptEl = document.querySelector<HTMLOListElement>("#transcript")!;
const audioSink = document.querySelector<HTMLDivElement>("#audio-sink")!;

const transcript = new TranscriptStore();
let room: Room | null = null;

function setStatus(state: string, text: string): void {
  statusEl.dataset.state = state;
  statusEl.textContent = text;
}

function renderTranscript(): void {
  transcriptEl.replaceChildren(
    ...transcript.list().map((seg) => {
      const li = document.createElement("li");
      li.classList.add(seg.final ? "final" : "interim");
      const who = document.createElement("span");
      who.className = "speaker";
      who.textContent = seg.speaker;
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
  const speaker = isLocal ? "You" : "Agent";

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
  }
}

function handleTrackUnsubscribed(track: RemoteTrack): void {
  track.detach().forEach((el) => el.remove());
}

async function connect(): Promise<void> {
  connectBtn.disabled = true;
  setStatus("connecting", "Fetching token…");
  try {
    const { token, url } = await fetchToken();

    room = new Room();
    room
      .on(RoomEvent.TrackSubscribed, handleTrackSubscribed)
      .on(RoomEvent.TrackUnsubscribed, handleTrackUnsubscribed)
      .on(RoomEvent.Disconnected, onDisconnected)
      .on(RoomEvent.ParticipantAttributesChanged, (attrs, participant) => {
        // The agent publishes its state (listening/thinking/speaking).
        const state = attrs["lk.agent.state"];
        if (state && participant.identity !== room?.localParticipant.identity) {
          setStatus("connected", `Connected — agent ${state}`);
        }
      });
    room.registerTextStreamHandler(TRANSCRIPTION_TOPIC, (reader, info) => {
      handleTranscription(reader, info).catch((err) =>
        console.error("transcription stream error", err),
      );
    });

    setStatus("connecting", "Connecting to LiveKit…");
    await room.connect(url, token);

    setStatus("connecting", "Publishing microphone…");
    await room.localParticipant.setMicrophoneEnabled(true);

    transcript.clear();
    renderTranscript();
    setStatus("connected", "Connected — speak whenever you like");
    connectBtn.textContent = "Disconnect";
  } catch (err) {
    console.error(err);
    setStatus("error", `Failed to connect: ${(err as Error).message}`);
    await teardown();
    connectBtn.textContent = "Connect";
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
  setStatus("disconnected", "Disconnected");
  connectBtn.textContent = "Connect";
  audioSink.replaceChildren();
  room = null;
}

connectBtn.addEventListener("click", () => {
  if (room) {
    void teardown();
  } else {
    void connect();
  }
});

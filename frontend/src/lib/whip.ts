/**
 * Minimal WHIP (WebRTC-HTTP Ingestion Protocol) publisher.
 *
 * Publishes a browser MediaStream (a selected webcam) to a WHIP endpoint —
 * here, mediamtx at http://localhost:8889/<path>/whip — which mediamtx then
 * serves as RTSP (rtsp://host.docker.internal:8554/<path>) for the dockerized
 * face-recognition service to read. This replaces the manual ffmpeg step.
 *
 * We prefer the H.264 codec so the RTSP stream mediamtx produces is decodable
 * by the OpenCV/FFmpeg reader in the face service.
 */

export interface WhipSession {
  pc: RTCPeerConnection;
  /** WHIP resource URL (Location header) for clean teardown, if provided. */
  resource: string | null;
  close: () => Promise<void>;
}

function waitForIceGathering(pc: RTCPeerConnection, timeoutMs = 2000): Promise<void> {
  return new Promise((resolve) => {
    if (pc.iceGatheringState === "complete") return resolve();
    const done = () => {
      pc.removeEventListener("icegatheringstatechange", check);
      clearTimeout(timer);
      resolve();
    };
    const check = () => {
      if (pc.iceGatheringState === "complete") done();
    };
    const timer = setTimeout(done, timeoutMs);
    pc.addEventListener("icegatheringstatechange", check);
  });
}

function preferH264(pc: RTCPeerConnection): void {
  try {
    const caps = RTCRtpSender.getCapabilities("video");
    if (!caps) return;
    const h264 = caps.codecs.filter((c) => c.mimeType.toLowerCase() === "video/h264");
    const rest = caps.codecs.filter((c) => c.mimeType.toLowerCase() !== "video/h264");
    if (!h264.length) return;
    for (const t of pc.getTransceivers()) {
      if (t.sender && t.sender.track && t.sender.track.kind === "video") {
        // setCodecPreferences may throw on unsupported browsers — ignore.
        t.setCodecPreferences([...h264, ...rest]);
      }
    }
  } catch {
    /* codec preference is best-effort */
  }
}

export async function whipPublish(stream: MediaStream, endpoint: string): Promise<WhipSession> {
  const pc = new RTCPeerConnection({ iceServers: [] }); // localhost: no STUN needed

  for (const track of stream.getVideoTracks()) {
    pc.addTransceiver(track, { direction: "sendonly" });
  }
  preferH264(pc);

  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);
  await waitForIceGathering(pc);

  let res: Response;
  try {
    res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/sdp" },
      body: pc.localDescription?.sdp ?? "",
    });
  } catch (e) {
    pc.close();
    throw new Error(
      `Could not reach the streaming server at ${endpoint}. Is mediamtx running? (${
        e instanceof Error ? e.message : e
      })`
    );
  }

  if (!res.ok) {
    pc.close();
    const body = await res.text().catch(() => "");
    throw new Error(`Streaming server rejected the publish (HTTP ${res.status}). ${body.slice(0, 200)}`);
  }

  const answer = await res.text();
  await pc.setRemoteDescription({ type: "answer", sdp: answer });

  const resource = res.headers.get("location");

  const close = async () => {
    try {
      if (resource) {
        const url = resource.startsWith("http")
          ? resource
          : new URL(resource, endpoint).toString();
        await fetch(url, { method: "DELETE" }).catch(() => {});
      }
    } finally {
      pc.getSenders().forEach((s) => s.track && s.track.stop());
      pc.close();
    }
  };

  return { pc, resource, close };
}

// Frame-accurate video control for the authoring timeline.
//
// HTML5 `video.currentTime = t` is NOT frame-exact: the browser lands on the
// nearest keyframe-decodable frame and the value you set is not necessarily the
// frame that gets painted. That mismatch is exactly what drifted our earlier
// overlays (landmarks from one frame drawn over another). The fix is
// requestVideoFrameCallback (rVFC): it fires when a specific frame is actually
// presented and hands back that frame's real `mediaTime`. We seek, wait for the
// decode, then read the presented frame's mediaTime and treat THAT as truth.

export interface FrameInfo {
  /** Presentation timestamp of the frame actually on screen, in seconds. */
  mediaTime: number;
  /** Monotonic frame counter (rVFC), or -1 when rVFC is unavailable. */
  presentedFrames: number;
}

const hasRVFC = (v: HTMLVideoElement): boolean =>
  typeof v.requestVideoFrameCallback === "function";

/** Resolve with the next presented frame's metadata (or currentTime fallback). */
export function nextPresentedFrame(video: HTMLVideoElement): Promise<FrameInfo> {
  return new Promise((resolve) => {
    if (!hasRVFC(video)) {
      resolve({ mediaTime: video.currentTime, presentedFrames: -1 });
      return;
    }
    video.requestVideoFrameCallback!((_now, md) => {
      resolve({ mediaTime: md.mediaTime, presentedFrames: md.presentedFrames });
    });
  });
}

/** Seek and resolve once the target frame has decoded (the `seeked` event). */
export function seekTo(video: HTMLVideoElement, time: number): Promise<void> {
  return new Promise((resolve) => {
    const clamped = Math.max(0, Math.min(time, video.duration || time));
    // Already there (within a tiny epsilon) → nothing to wait for.
    if (Math.abs(video.currentTime - clamped) < 1e-4) { resolve(); return; }
    const onSeeked = () => { video.removeEventListener("seeked", onSeeked); resolve(); };
    video.addEventListener("seeked", onSeeked);
    video.currentTime = clamped;
  });
}

/**
 * Seek so the frame at `time` is painted, then return its exact mediaTime.
 * Use this before running MediaPipe so detection runs on the visible frame.
 */
export async function seekToFrame(video: HTMLVideoElement, time: number): Promise<FrameInfo> {
  await seekTo(video, time);
  // rVFC only fires while the pipeline advances; a paused seek paints one frame,
  // which is enough for a single callback. Guard with a timeout fallback.
  return Promise.race([
    nextPresentedFrame(video),
    new Promise<FrameInfo>((res) =>
      setTimeout(() => res({ mediaTime: video.currentTime, presentedFrames: -1 }), 120),
    ),
  ]);
}

/**
 * Estimate frames-per-second. There is no direct API, so we snapshot two
 * consecutive presented frames and invert their mediaTime delta. Falls back to
 * `fallback` (default 30) when rVFC is missing or the delta is implausible.
 */
export async function measureFps(video: HTMLVideoElement, fallback = 30): Promise<number> {
  if (!hasRVFC(video)) return fallback;
  const wasPaused = video.paused;
  try {
    await video.play().catch(() => {});
    const a = await nextPresentedFrame(video);
    const b = await nextPresentedFrame(video);
    const dt = b.mediaTime - a.mediaTime;
    if (dt > 1e-4 && dt < 1) {
      const fps = Math.round(1 / dt);
      // Snap to the common rates so tiny measurement noise doesn't give 29/31.
      for (const r of [24, 25, 30, 50, 60]) if (Math.abs(fps - r) <= 1) return r;
      return fps;
    }
    return fallback;
  } finally {
    if (wasPaused) video.pause();
  }
}

/** Frame index of the currently displayed time on the fps grid. */
export const frameIndex = (time: number, fps: number): number => Math.round(time * fps);

/**
 * Step exactly one frame (dir = +1 / -1) on the fps grid and return the exact
 * mediaTime of the frame that lands on screen. We seek slightly past the frame
 * boundary (+half a frame) so the decoder resolves to the intended frame rather
 * than the one before it.
 */
export function stepFrame(
  video: HTMLVideoElement, dir: 1 | -1, fps: number,
): Promise<FrameInfo> {
  const idx = frameIndex(video.currentTime, fps) + dir;
  const target = Math.max(0, idx) / fps + 0.5 / fps;
  return seekToFrame(video, target);
}

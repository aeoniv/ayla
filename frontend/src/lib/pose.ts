// On-device MediaPipe pose extraction (client-side inference). We send only the
// landmark vectors to the server, which does the authoritative comparison.

import { FilesetResolver, PoseLandmarker } from "@mediapipe/tasks-vision";

let landmarker: PoseLandmarker | null = null;        // VIDEO mode (practice)
let imageLandmarker: PoseLandmarker | null = null;   // IMAGE mode (studio)

async function loadFileset() {
  return FilesetResolver.forVisionTasks(
    "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm",
  );
}

const opts = (delegate: "GPU" | "CPU", runningMode: "VIDEO" | "IMAGE") => ({
  baseOptions: {
    modelAssetPath:
      "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task",
    delegate,
  },
  runningMode,
  numPoses: 1,
  minPoseDetectionConfidence: 0.3,
  minPosePresenceConfidence: 0.3,
  minTrackingConfidence: 0.3,
});

// GPU is far cheaper on low-end phones; fall back to CPU where WebGL fails.
async function create(runningMode: "VIDEO" | "IMAGE"): Promise<PoseLandmarker> {
  const fileset = await loadFileset();
  try {
    return await PoseLandmarker.createFromOptions(fileset, opts("GPU", runningMode));
  } catch {
    return await PoseLandmarker.createFromOptions(fileset, opts("CPU", runningMode));
  }
}

// VIDEO mode tracks the pose between frames instead of running a full
// detection every time — much cheaper on low-end phones than IMAGE mode.
export async function initPose(): Promise<void> {
  if (!landmarker) landmarker = await create("VIDEO");
}

// IMAGE mode: full detection on a single painted frame. The studio seeks and
// pauses arbitrarily, which breaks VIDEO-mode tracking assumptions.
export async function initPoseImage(): Promise<void> {
  if (!imageLandmarker) imageLandmarker = await create("IMAGE");
}

/**
 * Extract a single 33x4 landmark frame [x, y, z, visibility] from a video
 * element at the current time. Returns null if no pose is detected.
 */
let lastTs = -1;
export function detect(video: HTMLVideoElement, timestampMs: number): number[][] | null {
  if (!landmarker) return null;
  // VIDEO mode requires strictly increasing timestamps.
  const ts = Math.max(Math.floor(timestampMs), lastTs + 1);
  lastTs = ts;
  const res = landmarker.detectForVideo(video, ts);
  const lms = res.landmarks?.[0];
  if (!lms || lms.length < 33) return null;
  return lms.map((l) => [l.x, l.y, l.z, l.visibility ?? 1]);
}

/** Detect on the exact current frame of a (usually paused/seeked) video. */
export function detectImage(video: HTMLVideoElement): number[][] | null {
  if (!imageLandmarker) return null;
  const res = imageLandmarker.detect(video);
  const lms = res.landmarks?.[0];
  if (!lms || lms.length < 33) return null;
  return lms.map((l) => [l.x, l.y, l.z, l.visibility ?? 1]);
}

// Left<->right landmark index pairs for a horizontal mirror. Flipping X alone
// moves the points but keeps the labels, so a mirrored "left wrist" would still
// be compared to the avatar's left wrist. Swapping the labels too puts the
// mirrored pose into the avatar's own coordinate frame.
const MIRROR_PAIRS: [number, number][] = [
  [1, 4], [2, 5], [3, 6], [7, 8], [9, 10],
  [11, 12], [13, 14], [15, 16], [17, 18], [19, 20], [21, 22],
  [23, 24], [25, 26], [27, 28], [29, 30], [31, 32],
];
const MIRROR_MAP: number[] = (() => {
  const m = Array.from({ length: 33 }, (_, i) => i);
  for (const [a, b] of MIRROR_PAIRS) { m[a] = b; m[b] = a; }
  return m;
})();

/**
 * Mirror a pose for a selfie (front) camera: flip X and relabel left<->right so
 * a user who MIRRORS the avatar ends up in the avatar's frame and matches it
 * index-to-index. Used for BOTH the on-screen skeleton and the vector we score,
 * so display and scoring never disagree.
 */
export function mirrorPose(lm: number[][]): number[][] {
  const out: number[][] = new Array(33);
  for (let i = 0; i < 33; i++) {
    const src = lm[MIRROR_MAP[i]];
    out[i] = [1 - src[0], src[1], src[2], src[3] ?? 1];
  }
  return out;
}

// MediaPipe Pose 33-point skeleton edges.
export const POSE_CONNECTIONS: [number, number][] = [
  [0, 1], [1, 2], [2, 3], [3, 7], [0, 4], [4, 5], [5, 6], [6, 8], [9, 10],
  [11, 12], [11, 13], [13, 15], [15, 17], [15, 19], [15, 21], [17, 19],
  [12, 14], [14, 16], [16, 18], [16, 20], [16, 22], [18, 20],
  [11, 23], [12, 24], [23, 24],
  [23, 25], [25, 27], [27, 29], [27, 31], [29, 31],
  [24, 26], [26, 28], [28, 30], [28, 32], [30, 32],
];

// Must mirror the server's REGIONS (pose-scoring pose.py) so client coloring
// matches the authoritative region_scores.
export const REGIONS: Record<string, number[]> = {
  head: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
  left_arm: [11, 13, 15, 17, 19, 21],
  right_arm: [12, 14, 16, 18, 20, 22],
  torso: [11, 12, 23, 24],
  left_leg: [23, 25, 27, 29, 31],
  right_leg: [24, 26, 28, 30, 32],
};
const REGION_OF: Record<number, string> = (() => {
  const m: Record<number, string> = {};
  for (const [name, idxs] of Object.entries(REGIONS)) for (const i of idxs) if (!(i in m)) m[i] = name;
  return m;
})();

// score 0..100 → red→green hue
function scoreColor(score: number | undefined, alpha = 1): string {
  if (score === undefined) return `rgba(120,220,255,${alpha})`; // neutral cyan
  const hue = Math.max(0, Math.min(120, score * 1.2));
  return `hsla(${hue}, 90%, 55%, ${alpha})`;
}

/**
 * Draw the live skeleton onto a canvas. `regionScores` (from matchCheckpoint)
 * colors each limb green→red by match quality; omit it for a neutral overlay.
 */
export interface Anchor { cx: number; cy: number; torso: number }

// Map normalized landmarks (0..1 in their source frame) to canvas pixels,
// matching how the source video is displayed (`fit`), optionally mirrored.
function mapPoints(
  landmarks: number[][], w: number, h: number,
  opts: { mirror?: boolean; srcAspect?: number; fit?: "cover" | "contain" },
): [number, number][] {
  let boxW = w, boxH = h, offX = 0, offY = 0;
  if (opts.srcAspect && opts.srcAspect > 0) {
    const canvasAspect = w / h;
    const cover = opts.fit === "cover";
    // contain = fit inside (letterbox); cover = fill + crop.
    const widthDriven = cover ? canvasAspect < opts.srcAspect : canvasAspect > opts.srcAspect;
    if (widthDriven) { boxH = h; boxW = h * opts.srcAspect; }
    else { boxW = w; boxH = w / opts.srcAspect; }
    offX = (w - boxW) / 2; offY = (h - boxH) / 2;
  }
  return landmarks.map(([x, y]) =>
    [(opts.mirror ? 1 - x : x) * boxW + offX, y * boxH + offY]);
}

// --- authoring overlay mapping (STRICTLY non-mirrored, frame-exact) ---------
// MediaPipe emits normalized coords in the SOURCE frame: origin top-left, x→right,
// y→down, no mirror. To overlay on the displayed video we map through the same
// letterbox the browser uses. Authoring always uses fit:"contain" so the whole
// frame is visible (nothing cropped) and every landmark is auditable. There is
// NO `1 - x` anywhere here — mirroring a reference is what corrupted earlier
// overlays; the author must see the pose exactly as the camera recorded it.
export interface ContentRect { offX: number; offY: number; cw: number; ch: number }

export function contentRect(
  w: number, h: number, srcAspect: number, fit: "cover" | "contain" = "contain",
): ContentRect {
  if (!srcAspect || srcAspect <= 0) return { offX: 0, offY: 0, cw: w, ch: h };
  const canvasAspect = w / h;
  const cover = fit === "cover";
  const widthDriven = cover ? canvasAspect < srcAspect : canvasAspect > srcAspect;
  let cw = w, ch = h;
  if (widthDriven) { ch = h; cw = h * srcAspect; }
  else { cw = w; ch = w / srcAspect; }
  return { offX: (w - cw) / 2, offY: (h - ch) / 2, cw, ch };
}

// normalized [0..1] → canvas px (forward). Inverse of pxToNorm.
export function normToPx(nx: number, ny: number, r: ContentRect): [number, number] {
  return [nx * r.cw + r.offX, ny * r.ch + r.offY];
}
// canvas px → normalized [0..1], clamped in-frame. Used when the author drags a
// landmark; exact inverse of normToPx so a drag round-trips with no drift.
export function pxToNorm(px: number, py: number, r: ContentRect): [number, number] {
  const nx = (px - r.offX) / (r.cw || 1);
  const ny = (py - r.offY) / (r.ch || 1);
  return [Math.min(1, Math.max(0, nx)), Math.min(1, Math.max(0, ny))];
}

const midOf = (pts: [number, number][], a: number, b: number): [number, number] =>
  [(pts[a][0] + pts[b][0]) / 2, (pts[a][1] + pts[b][1]) / 2];

// Where a pose's body sits (hip center + torso length) in canvas pixels — used
// to snap the student's skeleton onto the avatar's actual on-screen body.
export function skeletonAnchor(
  canvas: HTMLCanvasElement, landmarks: number[][],
  opts: { mirror?: boolean; srcAspect?: number; fit?: "cover" | "contain" },
): Anchor | null {
  if (!landmarks || landmarks.length < 33) return null;
  const pts = mapPoints(landmarks, canvas.width, canvas.height, opts);
  const hip = midOf(pts, 23, 24), sho = midOf(pts, 11, 12);
  return { cx: hip[0], cy: hip[1], torso: Math.hypot(sho[0] - hip[0], sho[1] - hip[1]) || 1 };
}

export function drawSkeleton(
  canvas: HTMLCanvasElement,
  landmarks: number[][],
  opts: {
    mirror?: boolean; regionScores?: Record<string, number>;
    srcAspect?: number; fit?: "cover" | "contain"; matchThreshold?: number;
    ghost?: boolean; clear?: boolean; alignTo?: Anchor;
  } = {},
): void {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const w = canvas.width, h = canvas.height;
  if (opts.clear !== false) ctx.clearRect(0, 0, w, h);

  const pts = mapPoints(landmarks, w, h, opts);

  // Snap this skeleton onto a target anchor (the avatar's on-screen body): move
  // its hip to the anchor's hip and scale so its torso matches the anchor's.
  if (opts.alignTo) {
    const hip = midOf(pts, 23, 24), sho = midOf(pts, 11, 12);
    const torso = Math.hypot(sho[0] - hip[0], sho[1] - hip[1]) || 1;
    const s = opts.alignTo.torso / torso;
    for (const p of pts) {
      p[0] = opts.alignTo.cx + (p[0] - hip[0]) * s;
      p[1] = opts.alignTo.cy + (p[1] - hip[1]) * s;
    }
  }

  const regScore = (i: number) => opts.regionScores?.[REGION_OF[i]];
  const th = opts.matchThreshold;
  // Per-bone color. When we have a threshold, go BINARY (green=matched,
  // red=not) with a matching glow so it's unmistakable which bones are right.
  const boneColor = (s: number | undefined): string => {
    if (opts.ghost) return "rgba(90,200,255,0.95)";            // avatar target skeleton
    if (s === undefined) return "rgba(120,220,255,0.9)";       // neutral (playing)
    if (th !== undefined) return s >= th ? "#2ecc71" : "#ff4d4d";
    return scoreColor(s, 0.9);                                  // gradient fallback
  };

  ctx.lineWidth = opts.ghost ? Math.max(3, w * 0.007) : Math.max(4, w * 0.008);
  ctx.lineCap = "round";
  for (const [a, b] of POSE_CONNECTIONS) {
    if ((landmarks[a][3] ?? 1) < 0.3 || (landmarks[b][3] ?? 1) < 0.3) continue;
    const s = opts.regionScores ? Math.min(regScore(a) ?? 100, regScore(b) ?? 100) : undefined;
    const matched = th !== undefined && s !== undefined && s >= th;
    ctx.strokeStyle = boneColor(s);
    ctx.shadowColor = opts.ghost ? "#5ac8ff" : (matched ? "#2ecc71" : "transparent");
    ctx.shadowBlur = opts.ghost ? 8 : (matched ? 14 : 0);
    ctx.beginPath(); ctx.moveTo(pts[a][0], pts[a][1]); ctx.lineTo(pts[b][0], pts[b][1]); ctx.stroke();
  }
  ctx.shadowBlur = 0;
  const r = Math.max(4, w * 0.009);
  for (let i = 0; i < landmarks.length; i++) {
    if ((landmarks[i][3] ?? 1) < 0.3) continue;
    ctx.fillStyle = boneColor(opts.regionScores ? regScore(i) : undefined);
    ctx.beginPath(); ctx.arc(pts[i][0], pts[i][1], r, 0, Math.PI * 2); ctx.fill();
  }
}

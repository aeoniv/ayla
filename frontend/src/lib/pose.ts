// On-device MediaPipe pose extraction (client-side inference). We send only the
// landmark vectors to the server, which does the authoritative comparison.

import { FilesetResolver, PoseLandmarker } from "@mediapipe/tasks-vision";

let landmarker: PoseLandmarker | null = null;

export async function initPose(): Promise<void> {
  if (landmarker) return;
  const fileset = await FilesetResolver.forVisionTasks(
    "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm",
  );
  landmarker = await PoseLandmarker.createFromOptions(fileset, {
    baseOptions: {
      modelAssetPath:
        "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task",
    },
    runningMode: "VIDEO",
    numPoses: 1,
  });
}

/**
 * Extract a single 33x4 landmark frame [x, y, z, visibility] from a video
 * element at the current time. Returns null if no pose is detected.
 */
export function detect(video: HTMLVideoElement, timestampMs: number): number[][] | null {
  if (!landmarker) return null;
  const res = landmarker.detectForVideo(video, timestampMs);
  const lms = res.landmarks?.[0];
  if (!lms || lms.length < 33) return null;
  return lms.map((l) => [l.x, l.y, l.z, l.visibility ?? 1]);
}

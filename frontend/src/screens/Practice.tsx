import { useCallback, useEffect, useRef, useState } from "react";
import {
  CheckpointMeta, CoachResult, coachNext, getCheckpoints, getFullVideo,
  matchCheckpoint, submitAttempt,
} from "../api/client";
import { detect, initPose } from "../lib/pose";

interface Props {
  movementId: string;
  styleId: string;
  onExit: () => void;
}

type Phase = "loading" | "playing" | "gating" | "scoring" | "done" | "error";

// Pose-gated guided flow: the reference video pauses at each checkpoint and
// resumes only when the student's live pose matches (server-authoritative).
export default function Practice({ movementId, styleId, onExit }: Props) {
  const [phase, setPhase] = useState<Phase>("loading");
  const [checkpoints, setCheckpoints] = useState<CheckpointMeta[]>([]);
  const [current, setCurrent] = useState(0);
  const [lastScore, setLastScore] = useState<number | null>(null);
  const [hint, setHint] = useState<string>("");
  const [coach, setCoach] = useState<CoachResult | null>(null);
  const [error, setError] = useState<string>("");

  const refVideo = useRef<HTMLVideoElement>(null);
  const camVideo = useRef<HTMLVideoElement>(null);
  const collected = useRef<{ index: number; landmarks: number[][] }[]>([]);
  const gateTimer = useRef<number | null>(null);

  // --- setup: full video + checkpoints + pose + webcam ---------------------
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [full, cps] = await Promise.all([
          getFullVideo(movementId),
          getCheckpoints(movementId, styleId),
          initPose(),
        ]);
        if (cancelled) return;
        setCheckpoints(cps.checkpoints);
        const stream = await navigator.mediaDevices.getUserMedia({ video: true });
        if (camVideo.current) {
          camVideo.current.srcObject = stream;
          await camVideo.current.play().catch(() => {});
        }
        if (refVideo.current && full.full_url) {
          refVideo.current.src = full.full_url;
        }
        setPhase("playing");
      } catch (e) {
        setError(String(e));
        setPhase("error");
      }
    })();
    return () => {
      cancelled = true;
      const s = camVideo.current?.srcObject as MediaStream | null;
      s?.getTracks().forEach((t) => t.stop());
      if (gateTimer.current) window.clearInterval(gateTimer.current);
    };
  }, [movementId, styleId]);

  // --- pause playback when we reach the current checkpoint's timestamp -----
  const onTimeUpdate = useCallback(() => {
    const v = refVideo.current;
    if (!v || phase !== "playing") return;
    const cp = checkpoints[current];
    if (cp && v.currentTime >= cp.timestamp_seconds) {
      v.pause();
      setPhase("gating");
    }
  }, [phase, checkpoints, current]);

  // --- gating loop: match the student's live pose to the checkpoint --------
  useEffect(() => {
    if (phase !== "gating") return;
    gateTimer.current = window.setInterval(async () => {
      const cam = camVideo.current;
      if (!cam) return;
      const landmarks = detect(cam, performance.now());
      if (!landmarks) return;
      try {
        const r = await matchCheckpoint(movementId, styleId, current, landmarks);
        setLastScore(r.score);
        setHint(r.matched ? "Matched!" : `Adjust your ${r.worst_region.replace("_", " ")}`);
        if (r.matched) {
          collected.current.push({ index: current, landmarks });
          if (gateTimer.current) window.clearInterval(gateTimer.current);
          advance();
        }
      } catch { /* keep trying on transient errors */ }
    }, 500);
    return () => { if (gateTimer.current) window.clearInterval(gateTimer.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, current]);

  function advance() {
    if (current + 1 < checkpoints.length) {
      setCurrent((c) => c + 1);
      setPhase("playing");
      refVideo.current?.play().catch(() => {});
    } else {
      finish();
    }
  }

  async function finish() {
    setPhase("scoring");
    try {
      await submitAttempt(movementId, styleId, collected.current);
      const c = await coachNext();
      setCoach(c);
      setPhase("done");
    } catch (e) {
      setError(String(e));
      setPhase("error");
    }
  }

  return (
    <div className="practice">
      <button className="exit" onClick={onExit}>✕</button>

      <video ref={refVideo} className="ref-video" playsInline muted onTimeUpdate={onTimeUpdate} />
      <video ref={camVideo} className="cam-video" playsInline muted />

      {phase === "loading" && <div className="center">Preparing camera & form…</div>}

      {(phase === "playing" || phase === "gating") && (
        <div className="hud">
          <div>Checkpoint {current + 1} / {checkpoints.length}</div>
          {phase === "gating" && <div className="gate">Hold the pose {lastScore !== null && `(${lastScore})`}</div>}
          {hint && <div className="hint">{hint}</div>}
        </div>
      )}

      {phase === "scoring" && <div className="center">Scoring your run…</div>}

      {phase === "done" && coach && (
        <div className="coach">
          <h3>Your coach</h3>
          <p>{coach.note}</p>
          {coach.suggested_next.movement_id && (
            <p className="next">Try next: {coach.suggested_next.movement_id}</p>
          )}
          <button onClick={onExit}>Back to feed</button>
        </div>
      )}

      {phase === "error" && (
        <div className="center">Something went wrong.<br />{error}<button onClick={onExit}>Back</button></div>
      )}
    </div>
  );
}

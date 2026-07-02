import { frameIndex } from "../../lib/video";

interface Marker { index: number; mediaTime: number; audited: boolean }

interface Props {
  duration: number;
  currentTime: number;
  fps: number;
  markers: Marker[];
  selected: number | null;
  playing: boolean;
  onTogglePlay: () => void;
  onScrub: (time: number) => void;
  onStepFrame: (dir: 1 | -1) => void;
  onAddMarker: () => void;
  onJumpMarker: (index: number) => void;
  onRemoveMarker: (index: number) => void;
}

const fmt = (t: number) => {
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
};

/**
 * Scrubbable timeline. The slider seeks continuously; the ◀▮▶ buttons step
 * exactly one frame on the fps grid (delegated to lib/video for frame accuracy);
 * "＋ Pose" drops a marker at the current frame. Markers render as ticks along
 * the track and are click-to-jump.
 */
export default function TimelineEditor({
  duration, currentTime, fps, markers, selected, playing,
  onTogglePlay, onScrub, onStepFrame, onAddMarker, onJumpMarker, onRemoveMarker,
}: Props) {
  const pct = (t: number) => (duration > 0 ? (t / duration) * 100 : 0);

  return (
    <div className="timeline">
      <div className="tl-readout">
        <span>{fmt(currentTime)} / {fmt(duration)}</span>
        <span className="tl-frame">frame {frameIndex(currentTime, fps)} @ {fps}fps</span>
      </div>

      <div className="tl-track-wrap">
        <input
          className="tl-scrub"
          type="range"
          min={0}
          max={Math.max(0.01, duration)}
          step={1 / Math.max(1, fps)}
          value={Math.min(currentTime, duration || 0)}
          onChange={(e) => onScrub(+e.target.value)}
        />
        <div className="tl-markers">
          {markers.map((m) => (
            <button
              key={m.index}
              className={`tl-tick${selected === m.index ? " sel" : ""}${m.audited ? " done" : ""}`}
              style={{ left: `${pct(m.mediaTime)}%` }}
              title={`Checkpoint ${m.index + 1} @ ${m.mediaTime.toFixed(3)}s${m.audited ? " (audited)" : ""}`}
              onClick={() => onJumpMarker(m.index)}
            />
          ))}
        </div>
      </div>

      <div className="tl-controls">
        <button className="tl-play" onClick={onTogglePlay} title={playing ? "Pause" : "Play"}>
          {playing ? "⏸" : "▶"}
        </button>
        <button onClick={() => onStepFrame(-1)} title="Step back one frame">◀</button>
        <button onClick={() => onStepFrame(1)} title="Step forward one frame">▶</button>
        <button className="tl-add" onClick={onAddMarker} title="Capture pose at current frame">
          ＋ Pose marker
        </button>
        {selected !== null && (
          <button className="tl-del" onClick={() => onRemoveMarker(selected)}>
            ✕ Remove marker
          </button>
        )}
      </div>
    </div>
  );
}

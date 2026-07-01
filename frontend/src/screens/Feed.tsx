import { useEffect, useRef, useState } from "react";
import { FeedItem, getFeed } from "../api/client";
import MovementCard from "../components/MovementCard";

interface Props {
  onPractice: (movementId: string, styleId: string) => void;
}

export default function Feed({ onPractice }: Props) {
  const [items, setItems] = useState<FeedItem[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getFeed()
      .then((f) => { setItems(f); setActiveId(f[0]?.movement_id ?? null); })
      .catch((e) => setError(String(e)));
  }, []);

  // Vertical Reels-style: the card most in view becomes "active" (autoplays).
  useEffect(() => {
    const root = containerRef.current;
    if (!root) return;
    const obs = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting && e.intersectionRatio > 0.6) {
            setActiveId((e.target as HTMLElement).dataset.mid ?? null);
          }
        }
      },
      { root, threshold: [0.6] },
    );
    root.querySelectorAll("[data-mid]").forEach((el) => obs.observe(el));
    return () => obs.disconnect();
  }, [items]);

  if (error) return <div className="center">Could not load feed.<br />{error}</div>;
  if (!items.length) return <div className="center">No movements yet.</div>;

  return (
    <div className="feed" ref={containerRef}>
      {items.map((it) => (
        <div key={it.movement_id} data-mid={it.movement_id} className="feed-slide">
          <MovementCard
            item={it}
            active={activeId === it.movement_id}
            onPractice={onPractice}
          />
        </div>
      ))}
    </div>
  );
}

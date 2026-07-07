import { useEffect, useRef, useState } from "react";
import { CoachResult, FeedItem, coachNext, getFeed } from "../api/client";
import MovementCard from "../components/MovementCard";
import Wallet from "../components/Wallet";
import { SettingsIcon, WalletIcon } from "../components/icons";

interface Props {
  isOwner: boolean;
  userId: string;
  onOpenAdmin: () => void;
  onPractice: (movementId: string, styleId: string) => void;
}

export default function Feed({ isOwner, userId, onOpenAdmin, onPractice }: Props) {
  const [items, setItems] = useState<FeedItem[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [walletOpen, setWalletOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Direct coach trigger — no full practice session needed, so the swarm
  // agent (ix64-agent-ayla via delivery-service's /coach/next proxy) can be
  // reached straight from the feed.
  const [coachOpen, setCoachOpen] = useState(false);
  const [coachLoading, setCoachLoading] = useState(false);
  const [coach, setCoach] = useState<CoachResult | null>(null);
  const [coachError, setCoachError] = useState<string | null>(null);

  function openCoach() {
    setCoachOpen(true); setCoachLoading(true); setCoach(null); setCoachError(null);
    coachNext()
      .then(setCoach)
      .catch((e) => setCoachError(String(e)))
      .finally(() => setCoachLoading(false));
  }

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
    <>
      <button className="wallet-btn" onClick={() => (isOwner ? onOpenAdmin() : setWalletOpen(true))}>
        {isOwner ? <SettingsIcon /> : <WalletIcon />}
      </button>
      <button className="coach-btn" onClick={openCoach}>Coach</button>
      <div className="feed" ref={containerRef}>
        {items.map((it) => (
          <div key={it.movement_id} data-mid={it.movement_id} className="feed-slide">
            <MovementCard
              item={it}
              active={activeId === it.movement_id}
              userId={userId}
              onPractice={onPractice}
            />
          </div>
        ))}
      </div>
      {walletOpen && <Wallet isOwner={isOwner} onClose={() => setWalletOpen(false)} />}
      {coachOpen && (
        <div className="coach-overlay" onClick={() => setCoachOpen(false)}>
          <div className="coach" onClick={(e) => e.stopPropagation()}>
            <h3>Your coach</h3>
            {coachLoading && <p>Thinking…</p>}
            {coachError && <p>Could not reach your coach.<br />{coachError}</p>}
            {coach && (
              <>
                <p>{coach.note}</p>
                {coach.suggested_next.movement_id && (
                  <p className="next">Try next: {coach.suggested_next.movement_id}</p>
                )}
              </>
            )}
            <button onClick={() => setCoachOpen(false)}>Close</button>
          </div>
        </div>
      )}
    </>
  );
}

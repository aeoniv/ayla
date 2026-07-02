import { useEffect, useState } from "react";
import { getMyPurchases, getRevenue, Purchase, Revenue } from "../api/client";

interface Props {
  isOwner: boolean;
  onClose: () => void;
}

// User-facing "what I own" + owner-only Stars earnings, pulled live from
// Telegram's ledger via the delivery-service /admin/revenue endpoint.
export default function Wallet({ isOwner, onClose }: Props) {
  const [purchases, setPurchases] = useState<Purchase[] | null>(null);
  const [revenue, setRevenue] = useState<Revenue | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    getMyPurchases().then((r) => setPurchases(r.purchases)).catch((e) => setErr(String(e)));
    if (isOwner) getRevenue().then(setRevenue).catch(() => {});
  }, [isOwner]);

  return (
    <div className="sheet" onClick={onClose}>
      <div className="sheet-body" onClick={(e) => e.stopPropagation()}>
        <div className="sheet-head">
          <h3>Wallet</h3>
          <button className="x" onClick={onClose}>✕</button>
        </div>

        {isOwner && (
          <section className="earn">
            <h4>Earnings (owner)</h4>
            {revenue ? (
              <>
                <p className="big">
                  ⭐ {revenue.balance_stars ?? 0}
                  <span className="sub"> balance</span>
                </p>
                <p className="sub">Recent income: ⭐{revenue.recent_income_stars} · {revenue.transaction_count} tx</p>
                <p className="hint">{revenue.note}</p>
              </>
            ) : (
              <p className="sub">No Star revenue yet — appears after the first real purchase.</p>
            )}
          </section>
        )}

        <section>
          <h4>My unlocks</h4>
          {err && <p className="sub">Couldn’t load purchases.</p>}
          {purchases && purchases.length === 0 && <p className="sub">Nothing unlocked yet.</p>}
          {purchases?.map((p, i) => (
            <div className="row" key={i}>
              <span>{p.movement_name ?? p.movement_id ?? "—"}</span>
              <span className="tag">{p.scope}</span>
            </div>
          ))}
        </section>
      </div>
    </div>
  );
}

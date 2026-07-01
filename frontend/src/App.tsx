import { useEffect, useState } from "react";
import { authTelegram, setSessionToken } from "./api/client";
import { getInitData, initTelegram } from "./lib/telegram";
import Feed from "./screens/Feed";
import Practice from "./screens/Practice";

type View = { name: "feed" } | { name: "practice"; movementId: string; styleId: string };

export default function App() {
  const [ready, setReady] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
  const [view, setView] = useState<View>({ name: "feed" });

  useEffect(() => {
    initTelegram();
    const initData = getInitData();
    if (!initData) { setAuthError("Open this app from inside Telegram."); return; }
    authTelegram(initData)
      .then((r) => { setSessionToken(r.session_token); setReady(true); })
      .catch((e) => setAuthError(String(e)));
  }, []);

  if (authError) return <div className="center">{authError}</div>;
  if (!ready) return <div className="center">Signing in…</div>;

  if (view.name === "practice") {
    return (
      <Practice
        movementId={view.movementId}
        styleId={view.styleId}
        onExit={() => setView({ name: "feed" })}
      />
    );
  }
  return (
    <Feed
      onPractice={(movementId, styleId) => setView({ name: "practice", movementId, styleId })}
    />
  );
}

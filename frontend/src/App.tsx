import { useEffect, useState } from "react";
import { authTelegram, setSessionToken } from "./api/client";
import { getInitData, initTelegram } from "./lib/telegram";
import Admin from "./screens/Admin";
import AuthorStudio from "./screens/AuthorStudio";
import Feed from "./screens/Feed";
import Practice from "./screens/Practice";

type View =
  | { name: "feed" }
  | { name: "practice"; movementId: string; styleId: string }
  | { name: "admin" }
  | { name: "author"; movementId?: string };

const DEV_OWNER = import.meta.env.VITE_DEV_OWNER === "true";

export default function App() {
  const [ready, setReady] = useState(DEV_OWNER);
  const [role, setRole] = useState(DEV_OWNER ? "owner" : "student");
  const [authError, setAuthError] = useState<string | null>(null);
  const [view, setView] = useState<View>(DEV_OWNER ? { name: "author" } : { name: "feed" });

  useEffect(() => {
    if (DEV_OWNER) return;
    initTelegram();
    const initData = getInitData();
    if (!initData) { setAuthError("Open this app from inside Telegram."); return; }
    authTelegram(initData)
      .then((r) => { setSessionToken(r.session_token); setRole(r.role); setReady(true); })
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
  if (view.name === "admin") {
    return (
      <Admin
        onExit={() => setView({ name: "feed" })}
        onOpenAuthor={(movementId) => setView({ name: "author", movementId })}
      />
    );
  }
  if (view.name === "author") {
    return (
      <AuthorStudio
        movementId={view.movementId}
        onExit={() => setView({ name: "admin" })}
      />
    );
  }
  return (
    <Feed
      isOwner={role === "owner"}
      onOpenAdmin={() => setView({ name: "admin" })}
      onPractice={(movementId, styleId) => setView({ name: "practice", movementId, styleId })}
    />
  );
}

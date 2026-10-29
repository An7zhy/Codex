"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, jsonBody } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { BusyLabel, Field, LoadingState } from "@/components/ui/primitives";
import { Brand } from "@/components/brand";

type Principal = { username: string; role: "viewer" | "operator" | "admin"; organization: string; instance_id: string; read_only_demo?: boolean };
const Access = createContext<Principal | null>(null);
export function useAccess() { return useContext(Access); }

export function AccessGate({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Principal | null>(null);
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(false), [error, setError] = useState("");
  useEffect(() => {
    api<Principal>("/auth/session").then(setUser).catch(() => {}).finally(() => setLoading(false));
    const expired = () => { try { Object.keys(sessionStorage).filter((key) => key.startsWith("logistics-draft:")).forEach((key) => sessionStorage.removeItem(key)); } catch {} setUser(null); setError("Your session ended. Sign in again."); };
    window.addEventListener("logistics-auth-expired", expired);
    return () => window.removeEventListener("logistics-auth-expired", expired);
  }, []);
  async function signIn(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    const values = new FormData(event.currentTarget);
    try {
      const principal = await api<Principal>("/auth/login", jsonBody({ username: values.get("username"), password: values.get("password") }));
      setUser(principal);
    } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }
  if (loading) return <main className="app-content"><LoadingState /></main>;
  if (!user) return <main className="access-page"><section className="panel access-card">
    <Brand /><h1>Organization sign in</h1>
    <p className="muted">Invited accounts only. Your administrator provisions this organization instance.</p>
    <form onSubmit={signIn}>
      <Field label="Account name"><input name="username" autoComplete="username" className="input" required maxLength={100} /></Field>
      <Field label="Password"><input name="password" type="password" autoComplete="current-password" className="input" required maxLength={256} /></Field>
      {error && <p className="inline-error" role="alert">{error}</p>}
      <Button type="submit" disabled={busy}><BusyLabel busy={busy}>Sign in</BusyLabel></Button>
    </form><p className="muted small">No public registration. Use HTTPS for a remote pilot.</p>
  </section></main>;
  return <Access.Provider value={user}>{children}</Access.Provider>;
}

export function AccountControl() {
  const user = useAccess();
  const [error, setError] = useState("");
  if (user?.read_only_demo) return <div className="account-control"><span>Synthetic demo · Read only</span></div>;
  return <div className="account-control"><span>{user?.organization} · {user?.username} ({user?.role})</span>
    <Button variant="ghost" size="sm" onClick={async () => {
      try { await api("/auth/logout", jsonBody({})); window.dispatchEvent(new Event("logistics-auth-expired")); }
      catch (err) { setError((err as Error).message); }
    }}>Sign out</Button>{error && <span role="alert">{error}</span>}</div>;
}

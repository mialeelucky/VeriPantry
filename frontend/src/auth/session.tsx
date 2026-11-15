// Demo persona sessions (frontend.md §4.3). The token lives in memory and in
// sessionStorage only; never in a URL, localStorage or a notification.

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { gatewayApi } from "../api/gateway";
import type { Person } from "../api/types";

interface Session {
  token: string | null;
  person: Person | null;
  signIn: (personaId: string) => Promise<Person>;
  signOut: () => void;
  ready: boolean;
}

const SessionContext = createContext<Session | null>(null);

/** In a browser tab: sessionStorage. Installed as an app: the app's own storage, so a
 *  tapped notification opens the app signed in (frontend.md §4.3). */
function store(): Storage {
  try {
    return matchMedia("(display-mode: standalone)").matches ? localStorage : sessionStorage;
  } catch {
    return sessionStorage;
  }
}

function read(key: string): { token: string; person: Person; expiresAt: string } | null {
  try {
    const raw = store().getItem(key);
    if (!raw) return null;
    const value = JSON.parse(raw);
    return new Date(value.expiresAt).getTime() > Date.now() ? value : null;
  } catch {
    return null;
  }
}

export function SessionProvider({
  children,
  storageKey = "vp.session",
  autoPersona,
}: {
  children: ReactNode;
  storageKey?: string;
  /** Sign in as this persona automatically (used by the recording layout's phone). */
  autoPersona?: string;
}) {
  const [state, setState] = useState(() => read(storageKey));
  const [ready, setReady] = useState(!autoPersona || !!read(storageKey));

  const signIn = useCallback(
    async (personaId: string) => {
      const r = await gatewayApi.session(personaId);
      const value = { token: r.token, person: r.person, expiresAt: r.expiresAt };
      try {
        store().setItem(storageKey, JSON.stringify(value));
      } catch {
        /* private mode: keep it in memory only */
      }
      setState(value);
      return r.person;
    },
    [storageKey],
  );

  const signOut = useCallback(() => {
    try {
      store().removeItem(storageKey);
    } catch {
      /* ignore */
    }
    setState(null);
  }, [storageKey]);

  useEffect(() => {
    if (autoPersona && (!state || state.person.id !== autoPersona)) {
      signIn(autoPersona).finally(() => setReady(true));
    }
  }, [autoPersona, state, signIn]);

  const value = useMemo<Session>(
    () => ({ token: state?.token ?? null, person: state?.person ?? null, signIn, signOut, ready }),
    [state, signIn, signOut, ready],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): Session {
  const s = useContext(SessionContext);
  if (!s) throw new Error("useSession outside SessionProvider");
  return s;
}

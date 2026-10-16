"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { mutate } from "swr";

const STORAGE_KEY = "taxproof.actingUser";
const DEFAULT_USER = "st-01";

type Ctx = { userId: string; setUserId: (id: string) => void };

const UserContext = createContext<Ctx>({ userId: DEFAULT_USER, setUserId: () => {} });

export function UserProvider({ children }: { children: React.ReactNode }) {
  const [userId, setState] = useState(DEFAULT_USER);

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(STORAGE_KEY);
      if (saved) setState(saved);
    } catch {}
  }, []);

  const setUserId = useCallback((id: string) => {
    setState(id);
    try {
      window.localStorage.setItem(STORAGE_KEY, id);
    } catch {}
    // Drop cached responses fetched under the previous identity (masking/permissions differ).
    mutate(() => true, undefined, { revalidate: true });
  }, []);

  return <UserContext.Provider value={{ userId, setUserId }}>{children}</UserContext.Provider>;
}

export const useActingUser = () => useContext(UserContext);

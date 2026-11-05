import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { api, setSignedOutHandler, tokens } from "./api";
import type { Me } from "./types";

interface AuthState {
  me: Me | null;
  loading: boolean;
  signIn: (login: string, password: string) => Promise<void>;
  refreshMe: () => Promise<void>;
  signOut: () => void;
  can: (permission: string) => boolean;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  const signOut = useCallback(() => {
    tokens.clear();
    setMe(null);
  }, []);

  useEffect(() => {
    setSignedOutHandler(() => setMe(null));
    if (!tokens.access) {
      setLoading(false);
      return;
    }
    api
      .get<Me>("/auth/me")
      .then(setMe)
      .catch(() => tokens.clear())
      .finally(() => setLoading(false));
  }, []);

  const signIn = useCallback(async (login: string, password: string) => {
    const result = await api.post<{ access_token: string; refresh_token: string }>("/auth/login", { login, password });
    tokens.set(result.access_token, result.refresh_token);
    setMe(await api.get<Me>("/auth/me"));
  }, []);

  const refreshMe = useCallback(async () => setMe(await api.get<Me>("/auth/me")), []);

  const can = useCallback((permission: string) => !!me?.permissions.includes(permission), [me]);

  return <AuthContext.Provider value={{ me, loading, signIn, signOut, can, refreshMe }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth outside AuthProvider");
  return value;
}

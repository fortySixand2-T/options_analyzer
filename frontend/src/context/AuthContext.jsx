import { createContext, useContext, useState, useCallback } from 'react';

const AuthContext = createContext(null);
const TOKEN_KEY = 'oa_access_token';
const REFRESH_KEY = 'oa_refresh_token';

function parseJwtPayload(token) {
  try {
    return JSON.parse(atob(token.split('.')[1]));
  } catch {
    return null;
  }
}

function isTokenValid(token) {
  const payload = parseJwtPayload(token);
  if (!payload?.exp) return false;
  return payload.exp * 1000 > Date.now();
}

function userFromToken(token) {
  const p = parseJwtPayload(token);
  if (!p?.sub || !p?.email) return null;
  return { id: parseInt(p.sub, 10), email: p.email };
}

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => {
    const t = localStorage.getItem(TOKEN_KEY);
    return t && isTokenValid(t) ? t : null;
  });

  const user = token ? userFromToken(token) : null;

  const login = useCallback(async (email, password) => {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data?.detail ?? 'Login failed');
    }
    const data = await res.json();
    localStorage.setItem(TOKEN_KEY, data.access_token);
    localStorage.setItem(REFRESH_KEY, data.refresh_token);
    setToken(data.access_token);
  }, []);

  const register = useCallback(async (email, password, displayName) => {
    const res = await fetch('/api/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password, display_name: displayName }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data?.detail ?? 'Registration failed');
    }
    const data = await res.json();
    localStorage.setItem(TOKEN_KEY, data.access_token);
    localStorage.setItem(REFRESH_KEY, data.refresh_token);
    setToken(data.access_token);
  }, []);

  const logout = useCallback(() => {
    const t = localStorage.getItem(TOKEN_KEY);
    if (t) {
      fetch('/api/auth/logout', {
        method: 'POST',
        headers: { Authorization: `Bearer ${t}` },
      }).catch(() => {});
    }
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(REFRESH_KEY);
    setToken(null);
  }, []);

  const refreshToken = useCallback(async () => {
    const rt = localStorage.getItem(REFRESH_KEY);
    if (!rt) {
      logout();
      return null;
    }
    try {
      const res = await fetch('/api/auth/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: rt }),
      });
      if (!res.ok) {
        logout();
        return null;
      }
      const data = await res.json();
      localStorage.setItem(TOKEN_KEY, data.access_token);
      localStorage.setItem(REFRESH_KEY, data.refresh_token);
      setToken(data.access_token);
      return data.access_token;
    } catch {
      logout();
      return null;
    }
  }, [logout]);

  const value = {
    user,
    token,
    login,
    register,
    logout,
    refreshToken,
    isAuthenticated: !!user,
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}

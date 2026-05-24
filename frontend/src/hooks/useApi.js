import { useState, useEffect, useCallback } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || '';
const TOKEN_KEY = 'oa_access_token';
const REFRESH_KEY = 'oa_refresh_token';

function authHeaders() {
  const token = localStorage.getItem(TOKEN_KEY);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function tryRefresh() {
  const rt = localStorage.getItem(REFRESH_KEY);
  if (!rt) return null;
  try {
    const res = await fetch(`${API_BASE}/api/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: rt }),
    });
    if (!res.ok) return null;
    const data = await res.json();
    localStorage.setItem(TOKEN_KEY, data.access_token);
    localStorage.setItem(REFRESH_KEY, data.refresh_token);
    return data.access_token;
  } catch {
    return null;
  }
}

async function authedFetch(url, init = {}) {
  const headers = { ...authHeaders(), ...(init.headers || {}) };
  let res = await fetch(url, { ...init, headers });

  if (res.status === 401) {
    const newToken = await tryRefresh();
    if (newToken) {
      headers.Authorization = `Bearer ${newToken}`;
      res = await fetch(url, { ...init, headers });
    } else {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(REFRESH_KEY);
      window.location.pathname = '/login';
      return new Promise(() => {});
    }
  }
  return res;
}

export function useApi(path, options = {}) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(!options.manual);
  const [error, setError] = useState(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authedFetch(`${API_BASE}${path}`);
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      const json = await res.json();
      setData(json);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    if (!options.manual) fetchData();
  }, [fetchData, options.manual]);

  return { data, loading, error, refetch: fetchData };
}

export async function postApi(path, body) {
  const res = await authedFetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export { authedFetch };

import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { setTokenGetter, setUnauthorizedHandler } from './api/client';
import Login from './pages/Login';
import Signup from './pages/Signup';
import Dashboard from './pages/Dashboard';
import OAuthCallback from './pages/OAuthCallback';
import Landing from './pages/Landing';
import React from 'react';
import { ThemeProvider } from './components/ThemeProvider';
import { useAuth } from './context/AuthContext';

function App() {
  const { user, loading, getIdToken, logout } = useAuth();
  const [sessionExpiredOpen, setSessionExpiredOpen] = React.useState(false);

  React.useEffect(() => {
    setTokenGetter(getIdToken);
  }, [getIdToken]);

  React.useEffect(() => {
    setUnauthorizedHandler(() => {
      setSessionExpiredOpen(true);
      setTimeout(() => {
        logout().finally(() => {
          window.location.href = '/login';
        });
      }, 800);
    });
  }, [logout]);

  return (
    <BrowserRouter>
      <ThemeProvider>
        {sessionExpiredOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
            <div className="w-full max-w-md rounded-2xl border border-border bg-card p-6 shadow-2xl">
              <h2 className="text-lg font-bold text-foreground">Session expired</h2>
              <p className="mt-2 text-sm text-muted-foreground">
                We couldn't validate your credentials. Please sign in again.
              </p>
              <div className="mt-5 flex justify-end">
                <button
                  className="rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground"
                  onClick={() => {
                    logout().finally(() => {
                      window.location.href = '/login';
                    });
                  }}
                >
                  Go to login
                </button>
              </div>
            </div>
          </div>
        )}
        <Routes>
          <Route path="/login" element={user ? <Navigate to="/app" replace /> : <Login />} />
          <Route path="/signup" element={user ? <Navigate to="/app" replace /> : <Signup />} />

          {/* OAuth popup callback — must be accessible without auth */}
          <Route path="/oauth-callback" element={<OAuthCallback />} />

          {/* Landing page (public). */}
          <Route path="/" element={<Landing />} />

          {/* Main app routes — all render Dashboard, which reads the URL */}
          <Route
            path="/app/*"
            element={
              <>
                {loading ? null : user ? (
                  <BackendWarmupGate>
                    <Dashboard />
                  </BackendWarmupGate>
                ) : (
                  <Navigate to="/login" replace />
                )}
              </>
            }
          />

          {/* Backwards compat: if anything hits root paths, keep UX sane */}
          <Route path="/*" element={loading ? null : user ? <Navigate to="/app" replace /> : <Navigate to="/" replace />} />
        </Routes>
      </ThemeProvider>
    </BrowserRouter>
  );
}

function BackendWarmupGate({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = React.useState(false);
  const [attempt, setAttempt] = React.useState(0);
  const [lastError, setLastError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;

    const normalizeBase = (raw?: string) => {
      const base = (raw || 'http://localhost:8000').replace(/\/+$/, '');
      return base.endsWith('/api') ? base.slice(0, -4) : base;
    };

    const baseUrl = normalizeBase(import.meta.env.VITE_API_URL);

    const checkOnce = async () => {
      try {
        const res = await fetch(`${baseUrl}/health`, { cache: 'no-store' });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        const data = (await res.json().catch(() => null)) as { status?: string } | null;
        if (data && data.status && data.status !== 'ok') {
          throw new Error('Not ready');
        }

        if (!cancelled) {
          setReady(true);
          setLastError(null);
        }
      } catch (e) {
        if (!cancelled) {
          setAttempt((a) => a + 1);
          setLastError(e instanceof Error ? e.message : 'Health check failed');
        }
      }
    };

    checkOnce();
    const id = window.setInterval(checkOnce, 2000);

    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  if (ready) return <>{children}</>;

  return (
    <div className="min-h-screen bg-background text-foreground flex items-center justify-center p-6">
      <div className="w-full max-w-xl rounded-3xl border border-border bg-card p-7 shadow-xl">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-2xl bg-primary/15 flex items-center justify-center">
            <div className="h-4 w-4 rounded-full border-2 border-primary border-t-transparent animate-spin" />
          </div>
          <div>
            <div className="text-lg font-bold">Starting backend…</div>
            <div className="text-sm text-muted-foreground">Please wait while we get things ready.</div>
          </div>
        </div>

        <div className="mt-5 flex items-center justify-between gap-4">
          <div className="text-xs text-muted-foreground">
            Attempts: {attempt}
            {lastError ? ` • Last: ${lastError}` : ''}
          </div>
          <button
            className="rounded-xl border border-border bg-card px-4 py-2 text-sm font-semibold text-foreground hover:bg-muted transition-colors"
            onClick={() => window.location.reload()}
          >
            Retry
          </button>
        </div>
      </div>
    </div>
  );
}

export default App;

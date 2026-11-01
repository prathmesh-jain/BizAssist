import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { setTokenGetter, setUnauthorizedHandler } from './api/client';
import React from 'react';
import { ThemeProvider } from './components/ThemeProvider';
import { useAuth } from './context/AuthContext';
import { postLoginPath } from './lib/session';
import { LogoMark } from './components/ui/Logo';

const Login = React.lazy(() => import('./pages/Login'));
const InvitePage = React.lazy(() => import('./pages/InvitePage'));
const Signup = React.lazy(() => import('./pages/Signup'));
const Dashboard = React.lazy(() => import('./pages/Dashboard'));
const OAuthCallback = React.lazy(() => import('./pages/OAuthCallback'));
const Landing = React.lazy(() => import('./pages/Landing'));

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
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/30 p-4">
            <div role="alertdialog" aria-modal="true" className="w-full max-w-sm rounded-lg border border-border bg-card p-6 shadow-xl">
              <h2 className="font-display text-xl font-medium text-foreground">You've been signed out</h2>
              <p className="mt-2 text-sm text-muted-foreground">
                Your session ended, so we couldn't confirm it's you. Sign in again to carry on.
              </p>
              <div className="mt-5 flex justify-end">
                <button
                  className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
                  onClick={() => {
                    logout().finally(() => {
                      window.location.href = '/login';
                    });
                  }}
                >
                  Sign in again
                </button>
              </div>
            </div>
          </div>
        )}
        <Routes>
          <Route path="/login" element={user ? <Navigate to={postLoginPath()} replace /> : <RouteSuspense><Login /></RouteSuspense>} />
          <Route path="/signup" element={user ? <Navigate to={postLoginPath()} replace /> : <RouteSuspense><Signup /></RouteSuspense>} />

          {/* Invitation links; redirects to login (and back) when signed out */}
          <Route path="/invite" element={<BackendWarmupGate><RouteSuspense><InvitePage /></RouteSuspense></BackendWarmupGate>} />

          {/* OAuth popup callback — must be accessible without auth */}
          <Route path="/oauth-callback" element={<RouteSuspense><OAuthCallback /></RouteSuspense>} />

          {/* Landing page (public). */}
          <Route path="/" element={<RouteSuspense><Landing /></RouteSuspense>} />

          {/* Main app routes — all render Dashboard, which reads the URL */}
          <Route
            path="/app/*"
            element={
              <>
                {loading ? null : user ? (
                  <BackendWarmupGate>
                    <RouteSuspense>
                      <Dashboard />
                    </RouteSuspense>
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

function RouteSuspense({ children }: { children: React.ReactNode }) {
  return (
    <React.Suspense fallback={<RouteLoader />}>
      {children}
    </React.Suspense>
  );
}

function RouteLoader() {
  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-6" aria-busy="true">
      <LogoMark className="w-9 h-9 animate-pulse" />
    </div>
  );
}

function BackendWarmupGate({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = React.useState(false);
  const [attempt, setAttempt] = React.useState(0);
  const [lastError, setLastError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    let timeoutId: number | undefined;

    const normalizeBase = (raw?: string) => {
      const base = (raw || "http://localhost:8000").replace(/\/+$/, "");
      return base.endsWith("/api") ? base.slice(0, -4) : base;
    };

    const baseUrl = normalizeBase(import.meta.env.VITE_API_URL);

    const pollHealth = async () => {
      try {
        const res = await fetch(`${baseUrl}/health`, {
          cache: "no-store",
        });

        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }

        const data = (await res.json().catch(() => null)) as
          | { status?: string }
          | null;

        if (data?.status !== "ok") {
          throw new Error("Backend not ready");
        }

        // Backend is ready → stop polling
        if (!cancelled) {
          setReady(true);
          setLastError(null);
        }

        return;
      } catch (e) {
        if (!cancelled) {
          setAttempt((a) => a + 1);
          setLastError(
            e instanceof Error ? e.message : "Health check failed"
          );

          // Schedule the next poll after 2 seconds
          timeoutId = window.setTimeout(pollHealth, 2000);
        }
      }
    };

    pollHealth();

    return () => {
      cancelled = true;

      if (timeoutId !== undefined) {
        window.clearTimeout(timeoutId);
      }
    };
  }, []);

  if (ready) return <>{children}</>;

  // Hosted backends can take a little while to wake up; say so plainly instead of spinning silently.
  const slow = attempt >= 3;
  return (
    <div className="min-h-screen bg-background text-foreground flex items-center justify-center p-6">
      <div className="w-full max-w-sm text-center rise-in">
        <LogoMark className="mx-auto w-10 h-10 animate-pulse" />
        <h1 className="mt-6 font-display text-2xl font-medium">
          {slow ? 'Still waking up…' : 'Getting things ready'}
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          {slow
            ? 'The server was asleep and is starting up. This can take up to a minute the first time.'
            : 'Connecting to BizAssist.'}
        </p>
        {slow && (
          <>
            <button
              className="mt-6 rounded-md border border-border px-4 py-2 text-sm font-medium hover:bg-muted"
              onClick={() => window.location.reload()}
            >
              Try again
            </button>
            {lastError && (
              <p className="mt-4 font-mono text-[11px] text-muted-foreground">
                attempt {attempt} · {lastError}
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export default App;

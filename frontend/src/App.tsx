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
                {loading ? null : user ? <Dashboard /> : <Navigate to="/login" replace />}
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

export default App;

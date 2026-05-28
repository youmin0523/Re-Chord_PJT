import { lazy, Suspense, useEffect } from "react";
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import Landing from "@/pages/Landing";
import { AppShell } from "@/components/AppShell";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { SkeletonCard } from "@/components/ui/Skeleton";

// Lazy-load the heavy routes — keeps the initial bundle below 500 kB.
// Landing remains eagerly imported so the marketing page hydrates instantly.
const Home = lazy(() => import("@/pages/Home"));
const Job = lazy(() => import("@/pages/Job"));
const LibraryPage = lazy(() => import("@/pages/LibraryPage"));
const PerformanceView = lazy(() => import("@/pages/PerformanceView"));
const Login = lazy(() => import("@/pages/Login"));
const AuthCallback = lazy(() => import("@/pages/AuthCallback"));
const SignupConsent = lazy(() =>
  import("@/components/auth/SignupConsent").then((m) => ({ default: m.SignupConsent })),
);

function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => { window.scrollTo(0, 0); }, [pathname]);
  return null;
}

function RouteFallback() {
  // Lightweight skeleton matched to the typical page shell so the layout
  // doesn't pop when content lazy-loads.
  return (
    <div className="max-w-4xl mx-auto px-6 py-10 sm:py-16 space-y-4">
      <SkeletonCard />
      <SkeletonCard />
    </div>
  );
}

export default function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <ScrollToTop />
        <AppShell>
          <Suspense fallback={<RouteFallback />}>
            <Routes>
              <Route path="/" element={<Landing />} />
              <Route path="/app" element={<Home />} />
              <Route path="/library" element={<LibraryPage />} />
              <Route path="/job/:id" element={<Job />} />
              <Route path="/perform/job/:id" element={<PerformanceView />} />
              <Route path="/perform/setlist/:setlistId" element={<PerformanceView />} />
              <Route path="/login" element={<Login />} />
              <Route path="/auth/callback" element={<AuthCallback />} />
              <Route path="/signup-consent" element={<SignupConsent />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Suspense>
        </AppShell>
      </BrowserRouter>
    </ErrorBoundary>
  );
}

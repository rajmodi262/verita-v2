import { lazy, Suspense } from "react";
import type { ComponentType, LazyExoticComponent } from "react";
import { createBrowserRouter, Navigate } from "react-router-dom";
import type { RouteObject } from "react-router-dom";

import { RequireAuth } from "./RequireAuth";

function page(Component: LazyExoticComponent<ComponentType>) {
  return (
    <Suspense
      fallback={
        <p role="status" aria-live="polite">
          Loading…
        </p>
      }
    >
      <Component />
    </Suspense>
  );
}

const LandingPage = lazy(() => import("../routes/landing/LandingPage"));
const LoginPage = lazy(() => import("../routes/login/LoginPage"));
const QueuePage = lazy(() => import("../routes/queue/QueuePage"));
const InvestigationPage = lazy(() => import("../routes/alert/InvestigationPage"));
const CapacityPage = lazy(() => import("../routes/capacity/CapacityPage"));
const CasesPage = lazy(() => import("../routes/cases/CasesPage"));
const CaseFilePage = lazy(() => import("../routes/case/CaseFilePage"));
const EvidenceRoomPage = lazy(() => import("../routes/evidence-room/EvidenceRoomPage"));
const NotFoundPage = lazy(() => import("../routes/not-found/NotFoundPage"));

export const routes: RouteObject[] = [
  { path: "/", element: page(LandingPage) },
  { path: "/login", element: page(LoginPage) },
  {
    element: <RequireAuth />,
    children: [
      { path: "/queue", element: page(QueuePage) },
      { path: "/alerts/:id", element: page(InvestigationPage) },
      { path: "/capacity", element: page(CapacityPage) },
      { path: "/cases", element: page(CasesPage) },
      { path: "/cases/:id", element: page(CaseFilePage) },
      { path: "/evidence-room", element: page(EvidenceRoomPage) },
      { path: "/app", element: <Navigate to="/queue" replace /> },
    ],
  },
  { path: "*", element: page(NotFoundPage) },
];

export function createRouter() {
  return createBrowserRouter(routes);
}

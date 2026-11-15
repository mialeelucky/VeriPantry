// App shell and routes (frontend.md §3).

import { Navigate, NavLink, Outlet, Route, Routes, useLocation, useNavigate, useParams } from "react-router-dom";
import { LogOut } from "lucide-react";
import { useSession } from "./auth/session";
import { Mark, cx } from "./components/ui";
import ApprovalFlow from "./screens/approvals/ApprovalFlow";
import ApprovalInbox from "./screens/approvals/ApprovalInbox";
import AuditOverview from "./screens/audit/AuditOverview";
import TransactionAudit from "./screens/audit/TransactionAudit";
import BuyFlow from "./screens/buy/BuyFlow";
import NotificationSettings from "./screens/NotificationSettings";
import SignIn from "./screens/SignIn";
import Stage from "./screens/Stage";

function Shell() {
  const { person, signOut } = useSession();
  const navigate = useNavigate();
  const links = [
    { to: "/buy", label: "Buy", show: person?.kind !== "staff" },
    { to: "/approvals", label: "Approvals", show: person?.kind === "approver" },
    { to: "/audit", label: "Audit", show: !!person },
  ].filter((l) => l.show);
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-line bg-bg/90 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-[1080px] items-center justify-between gap-3 px-4">
          <div className="flex items-center gap-5">
            <NavLink to="/buy" className="flex items-center gap-2 font-medium">
              <Mark /> <span className="hidden sm:inline">VeriPantry</span>
            </NavLink>
            <nav className="flex gap-1">
              {links.map((l) => (
                <NavLink
                  key={l.to}
                  to={l.to}
                  className={({ isActive }) => cx("rounded-full px-3 py-1.5 text-[13px]", isActive ? "bg-surface text-ink shadow-sm" : "text-ink-2 hover:text-ink")}
                >
                  {l.label}
                </NavLink>
              ))}
            </nav>
          </div>
          {person ? (
            <div className="flex items-center gap-2 text-[13px]">
              <span className="hidden text-ink-2 sm:inline">
                {person.displayName}
                <span className="text-ink-3"> · {person.kind === "staff" ? "Valio Aimo" : person.role}</span>
              </span>
              <button
                type="button"
                onClick={() => {
                  signOut();
                  navigate("/sign-in");
                }}
                className="rounded-full p-2 text-ink-2 hover:bg-muted"
                aria-label="Sign out"
              >
                <LogOut className="size-4" />
              </button>
            </div>
          ) : (
            <NavLink to="/sign-in" className="text-[13px] text-ink-2 hover:text-ink">
              Sign in
            </NavLink>
          )}
        </div>
      </header>
      <main className="px-4 py-6 sm:py-8">
        <Outlet />
      </main>
    </div>
  );
}

function RequireSignIn({ kinds, children }: { kinds?: ("approver" | "staff")[]; children: React.ReactNode }) {
  const { person } = useSession();
  const location = useLocation();
  if (!person) return <Navigate to={`/sign-in?next=${encodeURIComponent(location.pathname)}`} replace />;
  if (kinds && !kinds.includes(person.kind)) return <Navigate to={person.kind === "staff" ? "/audit" : "/approvals"} replace />;
  return <>{children}</>;
}

function ApprovalsRoute() {
  const navigate = useNavigate();
  const { approvalId } = useParams();
  return (
    <div className="mx-auto w-full max-w-[420px] overflow-hidden rounded-[20px] border border-line bg-bg sm:bg-surface">
      {approvalId ? (
        <ApprovalFlow key={approvalId} approvalId={approvalId} onBack={() => navigate("/approvals")} />
      ) : (
        <ApprovalInbox onOpen={(id) => navigate(`/approvals/${encodeURIComponent(id)}`)} />
      )}
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/stage" element={<Stage />} />
      <Route element={<Shell />}>
        <Route path="/" element={<Navigate to="/buy" replace />} />
        <Route path="/buy" element={<BuyFlow />} />
        <Route path="/buy/:transactionId" element={<BuyFlow />} />
        <Route path="/sign-in" element={<SignIn />} />
        <Route
          path="/approvals"
          element={
            <RequireSignIn kinds={["approver"]}>
              <ApprovalsRoute />
            </RequireSignIn>
          }
        />
        <Route
          path="/approvals/:approvalId"
          element={
            <RequireSignIn kinds={["approver"]}>
              <ApprovalsRoute />
            </RequireSignIn>
          }
        />
        <Route
          path="/settings/notifications"
          element={
            <RequireSignIn kinds={["approver"]}>
              <NotificationSettings />
            </RequireSignIn>
          }
        />
        <Route
          path="/audit"
          element={
            <RequireSignIn>
              <AuditOverview />
            </RequireSignIn>
          }
        />
        <Route
          path="/audit/:transactionId"
          element={
            <RequireSignIn>
              <TransactionAudit />
            </RequireSignIn>
          }
        />
        <Route path="*" element={<Navigate to="/buy" replace />} />
      </Route>
    </Routes>
  );
}

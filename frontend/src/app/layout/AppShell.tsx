import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { ROLE_LABELS, useLogout } from "../../api/auth";
import type { User } from "../../api/auth";
import { Tour } from "../../components/Tour";
import { Button } from "../../components/ui";
import { cx } from "../../lib/cx";
import { useTheme } from "../../lib/theme";

import styles from "./AppShell.module.css";

export const NAV_ITEMS = [
  { to: "/queue", label: "Alert queue" },
  { to: "/capacity", label: "Capacity planner" },
  { to: "/cases", label: "Case files" },
  { to: "/models", label: "Model governance" },
  { to: "/evidence-room", label: "Evidence room" },
] as const;

export function AppShell({ user }: { user: User }) {
  const { theme, toggle } = useTheme();
  const logout = useLogout();
  const navigate = useNavigate();
  const location = useLocation();

  const onLogout = () => {
    logout.mutate(undefined, { onSettled: () => void navigate("/login", { replace: true }) });
  };

  return (
    <div className={styles.shell}>
      <a href="#main" className={styles.skip}>
        Skip to content
      </a>
      <aside className={styles.rail}>
        <NavLink to="/" className={cx(styles.brand)}>
          <span className={styles.mark} aria-hidden="true">
            V
          </span>
          <span>Verita</span>
        </NavLink>
        <nav aria-label="Primary">
          <ul className={styles.navList}>
            {NAV_ITEMS.map((item) => (
              <li key={item.to}>
                <NavLink
                  to={item.to}
                  className={({ isActive }) => cx(styles.navLink, isActive && styles.active)}
                >
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
      </aside>
      <div className={styles.main}>
        <header className={styles.topbar}>
          <p className={styles.dataset}>Dataset: IBM AML (synthetic)</p>
          <div className={styles.user}>
            <span>
              <span className={styles.username}>{user.username}</span>
              <span className={styles.role}>{ROLE_LABELS[user.role]}</span>
            </span>
            <Button
              variant="ghost"
              onClick={toggle}
              aria-label={theme === "paper" ? "Switch to night theme" : "Switch to paper theme"}
            >
              {theme === "paper" ? "Night" : "Paper"}
            </Button>
            <Button variant="ghost" onClick={onLogout} busy={logout.isPending}>
              Sign out
            </Button>
          </div>
        </header>
        <main id="main" className={styles.content} tabIndex={-1}>
          {/* Keyed by route so every page makes an entrance. */}
          <div key={location.pathname} className={styles.page}>
            <Outlet />
          </div>
        </main>
        {user.role === "reviewer" ? <Tour /> : null}
      </div>
    </div>
  );
}

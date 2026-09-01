import { useEffect, useRef, useState, type ReactElement, type ReactNode } from "react";
import { NavLink } from "react-router-dom";

export type PublicShellMainMode = "constrained" | "full_bleed";

// Project Spec S0286: inline is the pre-existing shared/default geometry
// (nav claims a grid column when open); overlay is selected only by Home so
// the opened rail layers above the canvas instead of resizing it. PublicShell
// never inspects routes to choose between them -- the caller decides.
export type PublicShellNavigationLayout = "inline" | "overlay";

type PublicShellProps = {
  children: ReactNode;
  mainMode?: PublicShellMainMode;
  initialNavOpen?: boolean;
  navigationLayout?: PublicShellNavigationLayout;
};

// Placeholders per design/screens/home/content.md integration notes; replace
// with the real Atlas repository and portfolio routes once wired up.
const REPOSITORY_URL = "https://github.com/<owner>/<atlas-repo>";
const PORTFOLIO_PROJECTS_URL = "https://fabioaguiar.dev/#projetos";
const PORTFOLIO_CONTACT_URL = "https://fabioaguiar.dev/contact";

function HomeIcon() {
  return (
    <svg viewBox="0 0 24 24">
      <path d="M5 10.5 12 5l7 5.5M8.5 10v8h7v-8" />
    </svg>
  );
}

function ProjectsIcon() {
  return (
    <svg viewBox="0 0 24 24">
      <path d="M7 4.5h10v15H7z" />
      <path d="M10 8h4M10 12h4M10 16h4" />
    </svg>
  );
}

function GitHubIcon() {
  return (
    <svg viewBox="0 0 24 24">
      <path d="M12 3.5a8.5 8.5 0 0 0-2.69 16.56c.43.08.58-.18.58-.41v-1.43c-2.38.52-2.88-1.01-2.88-1.01-.39-.98-.95-1.24-.95-1.24-.77-.53.06-.52.06-.52.85.06 1.31.88 1.31.88.76 1.3 1.98.93 2.47.71.08-.55.3-.93.54-1.15-1.9-.22-3.9-.95-3.9-4.23 0-.93.33-1.69.87-2.29-.09-.22-.38-1.11.08-2.31 0 0 .72-.23 2.36.87a8.07 8.07 0 0 1 4.3 0c1.64-1.1 2.36-.87 2.36-.87.46 1.2.17 2.09.08 2.31.54.6.87 1.36.87 2.29 0 3.29-2.01 4.01-3.92 4.22.31.27.58.81.58 1.64v2.43c0 .23.15.49.59.41A8.5 8.5 0 0 0 12 3.5Z" />
    </svg>
  );
}

function ContactIcon() {
  return (
    <svg viewBox="0 0 24 24">
      <path d="M4 7h16v10H4z" />
      <path d="m5 8 7 5 7-5" />
    </svg>
  );
}

type NavItem = {
  key: string;
  label: string;
  icon: ReactElement;
} & ({ external: true; href: string } | { external: false; to: string });

const NAV_ITEMS: NavItem[] = [
  { key: "home", label: "Home", icon: <HomeIcon />, external: false, to: "/" },
  { key: "projetos", label: "Projects", icon: <ProjectsIcon />, external: true, href: PORTFOLIO_PROJECTS_URL },
  { key: "github", label: "GitHub", icon: <GitHubIcon />, external: true, href: REPOSITORY_URL },
  { key: "contato", label: "Contact", icon: <ContactIcon />, external: true, href: PORTFOLIO_CONTACT_URL },
];

function isDesktopViewport() {
  return typeof window !== "undefined" && window.matchMedia("(min-width: 768px)").matches;
}

// Project Spec S0130: an explicit, tested main-area mode -- never a
// route-name selector, `:has()`, or child-driven layout escape. Default
// stays "constrained" so every pre-existing public route is unaffected;
// only a route that explicitly requests "full_bleed" drops the centered
// main-width constraint for the outer route boundary.
export default function PublicShell({
  children,
  mainMode = "constrained",
  initialNavOpen,
  navigationLayout = "inline",
}: PublicShellProps) {
  const navToggleRef = useRef<HTMLButtonElement | null>(null);
  // Project Spec S0137: `initialNavOpen` governs only the first-render nav
  // state. Omitted, it preserves the existing viewport-derived default; an
  // explicit boolean initializes the rail regardless of viewport, and does
  // not turn the rail into a continuously controlled component.
  const [navOpen, setNavOpen] = useState<boolean>(() =>
    typeof initialNavOpen === "boolean" ? initialNavOpen : isDesktopViewport(),
  );
  const [isDesktop, setIsDesktop] = useState<boolean>(isDesktopViewport);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const mediaQuery = window.matchMedia("(min-width: 768px)");
    const handleChange = (event: MediaQueryListEvent) => setIsDesktop(event.matches);
    mediaQuery.addEventListener("change", handleChange);
    return () => mediaQuery.removeEventListener("change", handleChange);
  }, []);

  useEffect(() => {
    if (!navOpen || isDesktop) {
      return;
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") {
        return;
      }

      setNavOpen(false);
      navToggleRef.current?.focus();
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isDesktop, navOpen]);

  const closeMobileNav = () => {
    if (!isDesktop) {
      setNavOpen(false);
    }
  };

  return (
    <div
      className={`public-shell${navOpen ? " public-shell--nav-open" : ""}`}
      data-nav-layout={navigationLayout}
    >
      <button
        ref={navToggleRef}
        type="button"
        className="public-shell__nav-toggle"
        aria-label={navOpen ? "Hide navigation" : "Show navigation"}
        aria-expanded={navOpen}
        aria-controls="public-shell-nav"
        onClick={() => setNavOpen((open) => !open)}
      >
        <span aria-hidden="true" />
        <span aria-hidden="true" />
        <span aria-hidden="true" />
      </button>

      {navOpen && (navigationLayout === "overlay" || !isDesktop) && (
        <div
          className="public-shell__nav-overlay"
          aria-hidden="true"
          onClick={() => setNavOpen(false)}
        />
      )}

      <aside id="public-shell-nav" className="public-shell__nav" aria-label="Main navigation">
        <nav>
          <ul className="public-shell__nav-list">
            {NAV_ITEMS.map((item) => (
              <li key={item.key}>
                {item.external ? (
                  <a
                    className="public-shell__nav-link"
                    href={item.href}
                    target="_blank"
                    rel="noreferrer"
                    onClick={closeMobileNav}
                  >
                    <span className="public-shell__nav-icon" aria-hidden="true">
                      {item.icon}
                    </span>
                    <span className="public-shell__nav-label">{item.label}</span>
                  </a>
                ) : (
                  <NavLink
                    to={item.to}
                    end
                    className={({ isActive }) => "public-shell__nav-link" + (isActive ? " is-active" : "")}
                    onClick={closeMobileNav}
                  >
                    <span className="public-shell__nav-icon" aria-hidden="true">
                      {item.icon}
                    </span>
                    <span className="public-shell__nav-label">{item.label}</span>
                  </NavLink>
                )}
              </li>
            ))}
          </ul>
        </nav>
      </aside>

      <main
        className={
          mainMode === "full_bleed"
            ? "public-shell__main public-shell__main--full-bleed"
            : "app-shell public-shell__main"
        }
        data-main-mode={mainMode}
      >
        {children}
      </main>
    </div>
  );
}

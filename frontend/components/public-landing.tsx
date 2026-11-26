"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight, ArrowUpRight, Github, Menu, X } from "lucide-react";
import styles from "./public-landing.module.css";

const repositoryUrl = "https://github.com/gauravtiwarrii/pylake";
const documentationUrl = `${repositoryUrl}#readme`;

const navigation: { label: string; href: string; external?: boolean }[] = [
  { label: "Platform", href: "#platform" },
  { label: "Features", href: "#features" },
  { label: "Architecture", href: "#architecture" },
  { label: "Documentation", href: documentationUrl, external: true },
];

const capabilities = [
  {
    number: "01",
    title: "Bring data in",
    description:
      "Land CSV, JSON, NDJSON, Parquet, and XLSX datasets in a workspace built for the next step.",
    label: "INGESTION",
  },
  {
    number: "02",
    title: "Shape it with context",
    description:
      "Promote and transform immutable lakehouse versions, with schema and quality details alongside the data.",
    label: "LAKEHOUSE",
  },
  {
    number: "03",
    title: "Ask better questions",
    description:
      "Explore Silver and Gold tables with guarded, read-only SQL powered by DuckDB.",
    label: "SQL ANALYTICS",
  },
  {
    number: "04",
    title: "Make the work repeatable",
    description:
      "Build dependency-aware pipelines from source, transform, quality, SQL, and materialization steps.",
    label: "ORCHESTRATION",
  },
  {
    number: "05",
    title: "Know what changed",
    description:
      "Follow recorded versions and lineage, and inspect null counts, duplicates, and schema details.",
    label: "QUALITY & LINEAGE",
  },
  {
    number: "06",
    title: "Keep operations visible",
    description:
      "Review pipeline run metrics, worker health, and workspace-scoped audit activity.",
    label: "OBSERVABILITY",
  },
];

const architecture = [
  { number: "01", title: "Sources", detail: "CSV · JSON · Parquet · XLSX" },
  { number: "02", title: "Ingestion", detail: "FastAPI" },
  { number: "03", title: "Storage", detail: "PostgreSQL · MinIO · local" },
  { number: "04", title: "Processing", detail: "Polars · DuckDB" },
  { number: "05", title: "SQL", detail: "SQLGlot · DuckDB" },
  { number: "06", title: "Analytics", detail: "Workspace explorer" },
];

function EcosystemArtwork() {
  return (
    <div className={styles.artworkFrame}>
      <div className={styles.artworkGlow} aria-hidden="true" />
      <svg
        className={styles.artwork}
        viewBox="0 0 720 620"
        role="img"
        aria-labelledby="ecosystem-title ecosystem-description"
      >
        <title id="ecosystem-title">PyLake connected data ecosystem</title>
        <desc id="ecosystem-description">
          Three medallion layers orbit a lakehouse core, connected by fine data
          flows.
        </desc>
        <defs>
          <radialGradient id="core-light">
            <stop offset="0" stopColor="#e4c990" stopOpacity=".2" />
            <stop offset=".58" stopColor="#c9ad78" stopOpacity=".06" />
            <stop offset="1" stopColor="#c9ad78" stopOpacity="0" />
          </radialGradient>
          <linearGradient id="flow-gold" x1="0" x2="1" y1="0" y2="1">
            <stop offset="0" stopColor="#a77c49" stopOpacity=".16" />
            <stop offset=".52" stopColor="#d8bd87" stopOpacity=".88" />
            <stop offset="1" stopColor="#d8bd87" stopOpacity=".12" />
          </linearGradient>
          <linearGradient id="flow-silver" x1="1" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="#b9c3c0" stopOpacity=".1" />
            <stop offset=".55" stopColor="#b9c3c0" stopOpacity=".76" />
            <stop offset="1" stopColor="#b9c3c0" stopOpacity=".08" />
          </linearGradient>
          <filter id="soft-glow" x="-80%" y="-80%" width="260%" height="260%">
            <feGaussianBlur stdDeviation="9" />
          </filter>
        </defs>

        <circle cx="370" cy="304" r="248" fill="url(#core-light)" />
        <circle
          cx="370"
          cy="304"
          r="207"
          fill="none"
          stroke="#c9ad78"
          strokeOpacity=".13"
        />
        <circle
          cx="370"
          cy="304"
          r="168"
          fill="none"
          stroke="#d7d2c4"
          strokeOpacity=".1"
          strokeDasharray="1 9"
        />
        <ellipse
          cx="370"
          cy="304"
          rx="280"
          ry="112"
          transform="rotate(-28 370 304)"
          fill="none"
          stroke="url(#flow-gold)"
          strokeWidth="1.2"
        />
        <ellipse
          cx="370"
          cy="304"
          rx="254"
          ry="92"
          transform="rotate(32 370 304)"
          fill="none"
          stroke="url(#flow-silver)"
          strokeWidth="1"
        />
        <path
          d="M92 380C178 342 208 186 329 167c116-18 169 89 285 34"
          fill="none"
          stroke="#b88c57"
          strokeOpacity=".54"
          strokeWidth="1"
        />
        <path
          d="M130 221c84 88 125 218 250 235 96 14 150-83 235-87"
          fill="none"
          stroke="#b9c3c0"
          strokeOpacity=".38"
          strokeWidth="1"
        />
        <path
          d="M172 130c112 53 131 156 217 174s119-79 197-115"
          fill="none"
          stroke="#d7bd88"
          strokeOpacity=".32"
          strokeWidth="1"
        />
        <circle cx="370" cy="304" r="83" fill="#111310" stroke="#c9ad78" strokeOpacity=".45" />
        <circle cx="370" cy="304" r="68" fill="none" stroke="#e2d5b9" strokeOpacity=".12" />
        <circle cx="370" cy="304" r="91" fill="#d8bd87" fillOpacity=".08" filter="url(#soft-glow)" />
        <path
          d="M338 306l32-19 32 19-32 19-32-19Z"
          fill="none"
          stroke="#d8bd87"
          strokeOpacity=".84"
          strokeWidth="1.2"
        />
        <path
          d="M338 306v18l32 19 32-19v-18M370 325v18"
          fill="none"
          stroke="#d8bd87"
          strokeOpacity=".52"
          strokeWidth="1.1"
        />
        <text
          x="370"
          y="374"
          textAnchor="middle"
          fill="#aaa79d"
          fontSize="9"
          letterSpacing="3"
        >
          PYLAKE CORE
        </text>

        <g className={styles.orbit}>
          <circle cx="155" cy="186" r="22" fill="#171713" stroke="#b88c57" strokeOpacity=".68" />
          <circle cx="155" cy="186" r="4" fill="#c59b67" />
        </g>
        <g>
          <circle cx="574" cy="204" r="18" fill="#151716" stroke="#b9c3c0" strokeOpacity=".76" />
          <circle cx="574" cy="204" r="3.5" fill="#c3cbc8" />
        </g>
        <g>
          <circle cx="552" cy="453" r="24" fill="#171611" stroke="#d8bd87" strokeOpacity=".72" />
          <circle cx="552" cy="453" r="4" fill="#d8bd87" />
        </g>
        <circle cx="262" cy="104" r="2" fill="#d8bd87" />
        <circle cx="481" cy="115" r="1.6" fill="#b9c3c0" />
        <circle cx="116" cy="300" r="1.8" fill="#d8bd87" />
        <circle cx="620" cy="347" r="1.8" fill="#b9c3c0" />
        <circle cx="290" cy="508" r="1.6" fill="#d8bd87" />

        <g fill="#b7b2a7" fontSize="10" letterSpacing="1.5">
          <text x="114" y="150">BRONZE</text>
          <text x="596" y="201">SILVER</text>
          <text x="580" y="469">GOLD</text>
        </g>
      </svg>
      <div className={styles.artworkCaption}>
        <span>ONE CONNECTED DATA FLOW</span>
        <span>BRONZE <i /> SILVER <i /> GOLD</span>
      </div>
    </div>
  );
}

export default function PublicLanding() {
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    if (
      window.matchMedia("(prefers-reduced-motion: reduce)").matches ||
      !("IntersectionObserver" in window)
    ) {
      return;
    }

    document.documentElement.classList.add("landing-motion-ready");
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add(styles.isVisible);
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.12 },
    );
    document.querySelectorAll<HTMLElement>("[data-landing-reveal]").forEach((item) => {
      observer.observe(item);
    });

    return () => {
      observer.disconnect();
      document.documentElement.classList.remove("landing-motion-ready");
    };
  }, []);

  return (
    <div className={styles.site}>
      <a className={styles.skipLink} href="#main-content">
        Skip to content
      </a>
      <header className={styles.header}>
        <div className={styles.headerInner}>
          <Link className={styles.brand} href="/" aria-label="PyLake home">
            <span className={styles.brandMark} aria-hidden="true">
              PL
            </span>
            <span>PyLake</span>
          </Link>

          <nav className={styles.desktopNav} aria-label="Main navigation">
            {navigation.map((item) => (
              <a
                key={item.label}
                href={item.href}
                target={item.external ? "_blank" : undefined}
                rel={item.external ? "noreferrer" : undefined}
              >
                {item.label}
              </a>
            ))}
          </nav>

          <div className={styles.headerActions}>
            <a className={styles.githubLink} href={repositoryUrl} target="_blank" rel="noreferrer">
              <Github size={15} strokeWidth={1.7} />
              <span>GitHub</span>
            </a>
            <Link className={styles.signIn} href="/login">
              Sign in <ArrowUpRight size={14} />
            </Link>
            <button
              className={styles.menuButton}
              type="button"
              aria-label={menuOpen ? "Close navigation" : "Open navigation"}
              aria-expanded={menuOpen}
              aria-controls="mobile-navigation"
              onClick={() => setMenuOpen((open) => !open)}
            >
              {menuOpen ? <X size={20} /> : <Menu size={20} />}
            </button>
          </div>
        </div>
        <nav
          className={styles.mobileNav}
          id="mobile-navigation"
          aria-label="Mobile navigation"
          hidden={!menuOpen}
        >
          {navigation.map((item) => (
            <a
              key={item.label}
              href={item.href}
              target={item.external ? "_blank" : undefined}
              rel={item.external ? "noreferrer" : undefined}
              onClick={() => setMenuOpen(false)}
            >
              {item.label}
              {item.external && <ArrowUpRight size={14} />}
            </a>
          ))}
          <Link href="/login" onClick={() => setMenuOpen(false)}>
            Sign in <ArrowUpRight size={14} />
          </Link>
        </nav>
      </header>

      <main id="main-content">
        <section className={styles.hero} aria-labelledby="hero-title">
          <div className={styles.heroAtmosphere} aria-hidden="true" />
          <div className={styles.heroInner}>
            <div className={styles.heroCopy}>
              <p className={styles.eyebrow}>
                <span className={styles.eyebrowLine} />
                OPEN-SOURCE LAKEHOUSE PLATFORM
              </p>
              <h1 id="hero-title">
                Your data deserves
                <br />
                a better <em>universe.</em>
              </h1>
              <p className={styles.heroDescription}>
                One unified platform to ingest, transform, orchestrate and analyze
                data. Everything connected. Everything in flow.
              </p>
              <div className={styles.heroActions}>
                <Link className={styles.primaryAction} href="/workspaces">
                  Explore PyLake <ArrowRight size={16} />
                </Link>
                <a className={styles.secondaryAction} href={repositoryUrl} target="_blank" rel="noreferrer">
                  <Github size={16} strokeWidth={1.7} /> View on GitHub
                </a>
              </div>
              <div className={styles.heroFootnote}>
                <span>OPEN SOURCE</span>
                <span className={styles.footnoteDot} />
                <span>BUILT FOR THE FULL DATA JOURNEY</span>
              </div>
            </div>
            <div className={styles.heroVisual}>
              <EcosystemArtwork />
            </div>
          </div>
          <a className={styles.scrollCue} href="#platform" aria-label="Scroll to platform">
            <span>SCROLL TO EXPLORE</span>
            <span className={styles.scrollLine} />
          </a>
        </section>

        <section className={`${styles.platformSection} ${styles.reveal}`} id="platform" data-landing-reveal>
          <div className={styles.sectionEyebrow}>A CALMER WAY TO WORK WITH DATA</div>
          <div className={styles.platformGrid}>
            <h2>
              From first file
              <br />
              to <em>clear insight.</em>
            </h2>
            <div className={styles.platformCopy}>
              <p>
                PyLake brings the essential parts of a lakehouse together. Ingest
                data, shape it into trusted layers, query it, and orchestrate work
                without losing the thread between each step.
              </p>
              <a href="#features" className={styles.textLink}>
                See what connects <ArrowRight size={15} />
              </a>
            </div>
          </div>
          <div className={styles.flowRule} aria-hidden="true">
            <span>INGEST</span>
            <i />
            <span>REFINE</span>
            <i />
            <span>UNDERSTAND</span>
            <i />
            <span>DELIVER</span>
          </div>
        </section>

        <section className={`${styles.featuresSection} ${styles.reveal}`} id="features" data-landing-reveal>
          <div className={styles.sectionHeading}>
            <div>
              <div className={styles.sectionEyebrow}>THE PLATFORM</div>
              <h2>
                One flow.
                <br />
                <em>Every essential.</em>
              </h2>
            </div>
            <p>
              A focused set of tools for the real work of building and operating
              data products.
            </p>
          </div>
          <div className={styles.capabilityList}>
            {capabilities.map((capability) => (
              <article className={styles.capability} key={capability.number}>
                <span className={styles.capabilityNumber}>{capability.number}</span>
                <div className={styles.capabilityMain}>
                  <span className={styles.capabilityLabel}>{capability.label}</span>
                  <h3>{capability.title}</h3>
                </div>
                <p>{capability.description}</p>
                <span className={styles.capabilityArrow} aria-hidden="true">
                  <ArrowUpRight size={16} />
                </span>
              </article>
            ))}
          </div>
        </section>

        <section className={`${styles.layersSection} ${styles.reveal}`} data-landing-reveal>
          <div className={styles.layersIntro}>
            <div className={styles.sectionEyebrow}>THE MEDALLION MODEL</div>
            <h2>
              Raw to ready.
              <br />
              <em>With the story intact.</em>
            </h2>
            <p>
              Each layer adds meaning while keeping its source and version
              connected. Move forward with context, not copies you can’t trace.
            </p>
          </div>
          <div className={styles.layerFlow}>
            <article className={`${styles.layer} ${styles.bronze}`}>
              <span className={styles.layerIndex}>01 / SOURCE</span>
              <span className={styles.layerOrb} aria-hidden="true">
                <span />
              </span>
              <h3>Bronze</h3>
              <p>Original ingested data, preserved as the starting point.</p>
              <span className={styles.layerMeta}>LAND AS RECEIVED</span>
            </article>
            <div className={styles.layerConnector} aria-hidden="true">
              <span />
              <ArrowRight size={15} />
            </div>
            <article className={`${styles.layer} ${styles.silver}`}>
              <span className={styles.layerIndex}>02 / REFINE</span>
              <span className={styles.layerOrb} aria-hidden="true">
                <span />
              </span>
              <h3>Silver</h3>
              <p>Cleaned and transformed versions, with quality in view.</p>
              <span className={styles.layerMeta}>SHAPE WITH CONTEXT</span>
            </article>
            <div className={styles.layerConnector} aria-hidden="true">
              <span />
              <ArrowRight size={15} />
            </div>
            <article className={`${styles.layer} ${styles.gold}`}>
              <span className={styles.layerIndex}>03 / ANALYZE</span>
              <span className={styles.layerOrb} aria-hidden="true">
                <span />
              </span>
              <h3>Gold</h3>
              <p>Analytics-ready tables for read-only SQL and downstream work.</p>
              <span className={styles.layerMeta}>MAKE IT USEFUL</span>
            </article>
          </div>
        </section>

        <section className={`${styles.architectureSection} ${styles.reveal}`} id="architecture" data-landing-reveal>
          <div className={styles.sectionHeading}>
            <div>
              <div className={styles.sectionEyebrow}>UNDER THE SURFACE</div>
              <h2>
                A clear path
                <br />
                <em>through the stack.</em>
              </h2>
            </div>
            <p>
              Familiar, open technologies. A straightforward path from source
              files to workspace analytics.
            </p>
          </div>
          <ol className={styles.architectureFlow}>
            {architecture.map((step, index) => (
              <li className={styles.architectureStep} key={step.number}>
                <span className={styles.architectureNumber}>{step.number}</span>
                <h3>{step.title}</h3>
                <p>{step.detail}</p>
                {index < architecture.length - 1 && (
                  <span className={styles.architectureArrow} aria-hidden="true">
                    <ArrowRight size={14} />
                  </span>
                )}
              </li>
            ))}
          </ol>
          <p className={styles.architectureNote}>
            The API and worker share workspace-scoped metadata and execution
        state. Storage can use local files or private MinIO.
          </p>
        </section>

        <section className={`${styles.openSourceSection} ${styles.reveal}`} data-landing-reveal>
          <div className={styles.openSourceMark} aria-hidden="true">
            <span>PL</span>
            <i />
            <i />
            <i />
          </div>
          <div className={styles.openSourceCopy}>
            <div className={styles.sectionEyebrow}>OPEN BY DESIGN</div>
            <h2>
              Built in the open.
              <br />
              <em>Made to move forward.</em>
            </h2>
            <p>
              PyLake is an open-source project. Explore the code, follow the
              roadmap, or help shape what comes next.
            </p>
            <div className={styles.openSourceActions}>
              <a className={styles.primaryAction} href={repositoryUrl} target="_blank" rel="noreferrer">
                Explore the repository <ArrowUpRight size={16} />
              </a>
              <a className={styles.textLink} href={`${repositoryUrl}/issues`} target="_blank" rel="noreferrer">
                Contribute on GitHub <ArrowUpRight size={15} />
              </a>
            </div>
          </div>
          <div className={styles.stackList}>
            <span>THE STACK</span>
            <p>Next.js <i /> FastAPI <i /> PostgreSQL</p>
            <p>DuckDB <i /> Polars <i /> MinIO</p>
            <a href={`${repositoryUrl}/blob/main/LICENSE`} target="_blank" rel="noreferrer">
              MIT LICENSE <ArrowUpRight size={12} />
            </a>
          </div>
        </section>
      </main>

      <footer className={styles.footer}>
        <div className={styles.footerTop}>
          <Link className={styles.brand} href="/" aria-label="PyLake home">
            <span className={styles.brandMark} aria-hidden="true">
              PL
            </span>
            <span>PyLake</span>
          </Link>
          <p>One Platform. Every Data. Infinite Possibilities.</p>
          <div className={styles.footerLinks}>
            <a href="#platform">Platform</a>
            <a href="#features">Features</a>
            <a href="#architecture">Architecture</a>
            <a href={documentationUrl} target="_blank" rel="noreferrer">
              Docs
            </a>
            <a href={repositoryUrl} target="_blank" rel="noreferrer">
              GitHub <ArrowUpRight size={12} />
            </a>
          </div>
        </div>
        <div className={styles.footerBottom}>
          <span>© 2026 PyLake contributors</span>
          <a href={`${repositoryUrl}/blob/main/LICENSE`} target="_blank" rel="noreferrer">
            Open source under MIT
          </a>
          <Link href="/login">Sign in</Link>
        </div>
      </footer>
    </div>
  );
}

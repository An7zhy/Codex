"use client";
import { LanguageSwitcher, useI18n } from "@/lib/i18n/provider";

import Link from "next/link";
import { useEffect, useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import {
  ArrowDown,
  ArrowRight,
  ArrowUpRight,
  Box,
  ChartNoAxesCombined,
  CircleCheck,
  GitBranch,
  Layers3,
  MoveUpRight,
  Route,
  ShieldCheck,
} from "lucide-react";
import { Brand } from "@/components/brand";
import { Button } from "@/components/ui/button";
import { RoutingLens } from "@/components/routing-lens";
import { api, money, percent } from "@/lib/utils";
import type { Workspace } from "@/lib/types";

function PlatformPreview() {
  const { t } = useI18n();
  const [data, setData] = useState<Workspace | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    api<Workspace>("/workspace?dataset_id=demo", { signal: controller.signal })
      .then(setData)
      .catch((error) => {
        if (error.name !== "AbortError") setFailed(true);
      });
    return () => controller.abort();
  }, []);
  return (
    <div className="product-preview">
      <div className="preview-sidebar">
        <Layers3 size={24} />
        <span className="preview-active">{t("Overview")}</span>
        <span>{t("Shipments")}</span>
        <span>{t("Exceptions")}</span>
        <span>{t("Decisions")}</span>
        <span>{t("Optimization")}</span>
        <span>{t("Analytics")}</span>
      </div>
      <div className="preview-main">
        <div className="preview-title">
          <div>
            <span className="live-dot" /> {t(" Synthetic Demo Data")}
            <h3>{t("Your network. In perspective.")}</h3>
          </div>
          <Link href="/app" aria-label={t("Open interactive platform preview")}>
            <ArrowUpRight size={21} />
          </Link>
        </div>
        {failed ? (
          <p className="muted">
            {t(
              "Sign in to the protected platform to explore the computed synthetic demo. No private workspace data is public.",
            )}
          </p>
        ) : (
          <>
            <div className="preview-metrics">
              {[
                ["Shipments", data?.kpis.total_shipments?.toString()],
                [
                  "On-time delivery",
                  data ? percent(data.kpis.on_time_delivery_rate) : undefined,
                ],
                [
                  "Shipping cost",
                  data ? money(data.kpis.total_shipping_cost) : undefined,
                ],
              ].map(([label, value]) => (
                <div key={label}>
                  <span>{t(label)}</span>
                  <strong>{t(value ?? "—")}</strong>
                </div>
              ))}
            </div>
            <div className="preview-table">
              <div className="preview-table-head">
                <span>{t("Shipment")}</span>
                <span>{t("Transport")}</span>
                <span>{t("Priority")}</span>
              </div>
              {(data?.exceptions ?? []).slice(0, 3).map((row) => (
                <div key={row.source_row}>
                  <span>{row.shipment_id}</span>
                  <span>{t(row.transport_mode)}</span>
                  <span className="preview-priority">
                    {t(row.priority_level)}
                  </span>
                </div>
              ))}
            </div>
            <p className="preview-foot">
              {t(
                "Computed by the Python rules engine. Every figure has a definition.",
              )}
            </p>
          </>
        )}
      </div>
    </div>
  );
}

export function Landing() {
  const { t } = useI18n();
  const reduce = useReducedMotion();
  return (
    <div className="marketing">
      <header className="marketing-nav">
        <Brand />
        <LanguageSwitcher />
        <nav aria-label={t("Main navigation")}>
          <a href="#platform">{t("Platform")}</a>
          <a href="#intelligence">{t("Intelligence")}</a>
          <a href="#architecture">{t("Architecture")}</a>
        </nav>
        <Button asChild variant="outline" size="sm">
          <Link href="/app">
            {t("Launch platform ")}
            <ArrowUpRight size={15} />
          </Link>
        </Button>
      </header>
      <main id="main-content">
        <section className="hero">
          <RoutingLens />
          <motion.div
            className="hero-copy"
            initial={reduce ? false : { y: 12 }}
            animate={{ y: 0 }}
            transition={{ duration: 0.65, ease: [0.22, 1, 0.36, 1] }}
          >
            <div className="hero-kicker">
              <span className="live-dot" />
              {t("Clarity across the supply chain")}
            </div>
            <h1>
              {t("Intelligence")}
              <br />
              {t("behind every")}
              <br />
              {t("shipment.")}
            </h1>
            <p>
              {t(
                "Turn complex logistics data into explainable decisions with optimization, risk analysis, and intelligent workflows.",
              )}
            </p>
            <div className="hero-actions">
              <Button asChild>
                <Link href="/app">
                  {t("Launch platform ")}
                  <ArrowUpRight size={18} />
                </Link>
              </Button>
              <a className="quiet-link" href="#platform">
                {t("Explore the possibilities ")}
                <ArrowDown size={15} />
              </a>
            </div>
            <p className="hero-disclaimer">
              {t(
                "Independent engineering prototype. Powered by synthetic data.",
              )}
            </p>
          </motion.div>
          <div className="hero-bottom">
            <span>
              {t("From operational noise to a decision you can explain.")}
            </span>
            <a href="#platform" aria-label={t("Explore platform capabilities")}>
              <ArrowDown size={17} />
            </a>
          </div>
        </section>
        <section className="capability-strip">
          <span>
            <ShieldCheck />
            {t("Explainable by design")}
          </span>
          <span>
            <Route />
            {t("Constraint-aware optimization")}
          </span>
          <span>
            <GitBranch />
            {t("Reproducible scenarios")}
          </span>
          <span>
            <Box />
            {t("Your data stays local")}
          </span>
        </section>
        <section id="platform" className="marketing-section platform-section">
          <div className="section-intro">
            <div>
              <p className="section-kicker">{t("The platform")}</p>
              <h2>
                {t("See the exception.")}
                <br />
                {t("Understand the decision.")}
              </h2>
            </div>
            <p>
              {t(
                "One connected workspace to examine shipment performance, prioritize what needs attention, and compare the paths forward.",
              )}
            </p>
          </div>
          <PlatformPreview />
          <div className="feature-trio">
            <article>
              <div className="feature-icon">
                <ChartNoAxesCombined />
              </div>
              <h3>{t("A complete operational picture")}</h3>
              <p>
                {t(
                  "Bring CSV and Excel orders into a consistent view. Inspect delivery KPIs, carrier performance and data quality.",
                )}
              </p>
              <Link href="/app">
                {t("Explore overview ")}
                <MoveUpRight size={14} />
              </Link>
            </article>
            <article>
              <div className="feature-icon">
                <ShieldCheck />
              </div>
              <h3>{t("Focus where it matters")}</h3>
              <p>
                {t(
                  "Explainable priorities surface active exceptions. Missing evidence stays visible, instead of becoming false confidence.",
                )}
              </p>
              <Link href="/app/exceptions">
                {t("Review exceptions ")}
                <MoveUpRight size={14} />
              </Link>
            </article>
            <article>
              <div className="feature-icon">
                <Route />
              </div>
              <h3>{t("Make the trade-offs explicit")}</h3>
              <p>
                {t(
                  "Compare cost, time and simulated risk while respecting the same budget, deadline and shared-capacity constraints.",
                )}
              </p>
              <Link href="/app/optimization">
                {t("Explore optimization ")}
                <MoveUpRight size={14} />
              </Link>
            </article>
          </div>
        </section>
        <section
          id="intelligence"
          className="marketing-section intelligence-section"
        >
          <div className="intelligence-copy">
            <p className="section-kicker">{t("Decision intelligence")}</p>
            <h2>
              {t("Powerful reasoning.")}
              <br />
              {t("A visible rationale.")}
            </h2>
            <p>
              {t(
                "Go beyond identifying a late shipment. Explore alternatives, understand the assumptions, and keep a record of the choice.",
              )}
            </p>
            <ul>
              <li>
                <CircleCheck />
                {t("Deterministic rules with transparent scoring")}
              </li>
              <li>
                <CircleCheck />
                {t("Shared-capacity allocation with OR-Tools")}
              </li>
              <li>
                <CircleCheck />
                {t("Monte Carlo evaluation with a fixed random seed")}
              </li>
              <li>
                <CircleCheck />
                {t("Persistent handling history and recorded outcomes")}
              </li>
            </ul>
            <Button asChild variant="outline">
              <Link href="/app/decisions">
                {t("Enter the decision center ")}
                <ArrowUpRight size={16} />
              </Link>
            </Button>
          </div>
          <div
            className="decision-visual"
            aria-label={t("Decision process diagram")}
          >
            <div className="decision-node">
              <Box />
              <div>
                {t("Shipment context")}
                <small>{t("Deadlines, costs, available evidence")}</small>
              </div>
            </div>
            <div className="decision-connector" />
            <div className="decision-core">
              <div className="core-symbol">
                <GitBranch size={36} />
              </div>
              <strong>{t("Explainable decision engine")}</strong>
              <span>{t("Rules. Constraints. Assumptions.")}</span>
            </div>
            <div className="decision-branches">
              <span />
              <span />
              <span />
            </div>
            <div className="decision-options">
              <div>{t("Monitor")}</div>
              <div>{t("Expedite")}</div>
              <div>{t("Reroute")}</div>
            </div>
            <p>
              {t("Hypothetical alternatives. Human judgment stays in control.")}
            </p>
          </div>
        </section>
        <section
          id="architecture"
          className="marketing-section architecture-section"
        >
          <div className="section-intro">
            <div>
              <p className="section-kicker">{t("Built to be understood")}</p>
              <h2>
                {t("Modern on the surface.")}
                <br />
                {t("Grounded underneath.")}
              </h2>
            </div>
            <p>
              {t(
                "A new interface over independently tested Python logic. Every chart, score and allocation comes from the same calculation engine.",
              )}
            </p>
          </div>
          <div className="architecture-row">
            <div>
              <span>{t("Experience")}</span>
              <h3>{t("Next.js + React")}</h3>
              <p>
                {t(
                  "Responsive, accessible workspaces with real application routes.",
                )}
              </p>
            </div>
            <ArrowRight />
            <div>
              <span>{t("Analysis")}</span>
              <h3>{t("Python + FastAPI")}</h3>
              <p>
                {t(
                  "pandas rules, explainable scoring and deterministic reporting.",
                )}
              </p>
            </div>
            <ArrowRight />
            <div>
              <span>{t("Decision + memory")}</span>
              <h3>{t("OR-Tools + SQLite")}</h3>
              <p>
                {t(
                  "Constraint-based allocation and persistent local case records.",
                )}
              </p>
            </div>
          </div>
          <p className="architecture-note">
            {t(
              "No paid AI API. No live carrier network. Simulated reliability is not verified carrier performance.",
            )}
          </p>
        </section>
        <section className="marketing-cta">
          <div>
            <p className="section-kicker">{t("A clearer next move")}</p>
            <h2>
              {t("Put intelligence")}
              <br />
              {t("into motion.")}
            </h2>
          </div>
          <Button asChild>
            <Link href="/app">
              {t("Launch platform ")}
              <ArrowUpRight size={20} />
            </Link>
          </Button>
        </section>
      </main>
      <footer className="marketing-footer">
        <Brand compact />
        <p>{t("An independent logistics engineering prototype.")}</p>
        <div>
          <a
            href="https://github.com/An7zhy/Codex/tree/feature/premium-web-redesign"
            target="_blank"
            rel="noreferrer"
          >
            {t("Source code ")}
            <ArrowUpRight size={13} />
          </a>
          <Link href="/app/settings">{t("Methodology")}</Link>
        </div>
      </footer>
    </div>
  );
}

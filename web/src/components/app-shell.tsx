"use client";
import { LanguageSwitcher, useI18n } from "@/lib/i18n/provider";

import { useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import * as Dialog from "@radix-ui/react-dialog";
import {
  ArrowUpRight,
  BarChart3,
  Box,
  ChartNoAxesCombined,
  ChevronRight,
  CircleHelp,
  GitBranch,
  LayoutDashboard,
  Menu,
  Settings2,
  ShieldAlert,
  Upload,
  X,
} from "lucide-react";
import { Brand } from "@/components/brand";
import { Button } from "@/components/ui/button";
import { Badge, BusyLabel, Field } from "@/components/ui/primitives";
import {
  WorkspaceProvider,
  useWorkspace,
} from "@/components/workspace-provider";
import { api } from "@/lib/utils";
import type { Dataset } from "@/lib/types";
import { AccessGate, AccountControl, useAccess } from "@/components/access";

const navigation = [
  { href: "/app", label: "Overview", icon: LayoutDashboard },
  { href: "/app/shipments", label: "Shipments", icon: Box },
  { href: "/app/exceptions", label: "Exceptions", icon: ShieldAlert },
  { href: "/app/decisions", label: "Decision Center", icon: GitBranch },
  {
    href: "/app/optimization",
    label: "Optimization",
    icon: ChartNoAxesCombined,
  },
  { href: "/app/analytics", label: "Analytics", icon: BarChart3 },
  { href: "/app/settings", label: "Settings", icon: Settings2 },
];
function Navigation({ close }: { close?: () => void }) {
  const { t } = useI18n();
  const path = usePathname();
  return (
    <>
      <p className="workspace-label">{t("Operations workspace")}</p>
      <nav className="app-nav" aria-label={t("Platform navigation")}>
        {navigation.map((item) => (
          <Link
            onClick={close}
            key={item.href}
            href={item.href}
            className={
              (
                item.href === "/app"
                  ? path === item.href
                  : path.startsWith(item.href)
              )
                ? "active"
                : ""
            }
            aria-current={
              (
                item.href === "/app"
                  ? path === item.href
                  : path.startsWith(item.href)
              )
                ? "page"
                : undefined
            }
          >
            <item.icon strokeWidth={1.6} />
            {t(item.label)}
            {item.label === "Optimization" && (
              <span className="nav-index">{t("V3")}</span>
            )}
          </Link>
        ))}
      </nav>
    </>
  );
}

function UploadDialog() {
  const { t } = useI18n();
  const user = useAccess();
  const [open, setOpen] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const { asOf, selectDataset, notify } = useWorkspace();
  const [date, setDate] = useState(asOf);
  const [preview, setPreview] = useState<{
    confirmation: string;
    rules: Record<string, string>;
    kpis: Record<string, number>;
    issue_count: number;
    duplicate_rows: number;
    date_precision: unknown;
    conflict_preview: unknown;
    issues: unknown;
    sample: unknown;
  } | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  async function upload(event: React.FormEvent) {
    event.preventDefault();
    if (!file) {
      setError("Choose a CSV or Excel file first.");
      return;
    }
    if (file.size > 20 * 1024 * 1024) {
      setError("The file exceeds 20 MB. Split it into smaller datasets.");
      return;
    }
    setBusy(true);
    setError("");
    const form = new FormData();
    form.append("file", file);
    form.append("as_of", date);
    try {
      if (!preview) {
        const result = await api<NonNullable<typeof preview>>(
          "/datasets/preview",
          { method: "POST", body: form },
        );
        setPreview(result);
        setConfirmed(false);
        return;
      }
      if (!confirmed) {
        setError("Review and confirm the import rules first.");
        return;
      }
      form.append("confirmed", preview.confirmation);
      const data = await api<Dataset>("/datasets", {
        method: "POST",
        body: form,
      });
      selectDataset(data);
      setOpen(false);
      setFile(null);
      notify("Dataset uploaded. Analysis is ready.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog.Root
      open={open}
      onOpenChange={(value) => {
        setOpen(value);
        if (value) {
          setDate(asOf);
          setError("");
          setPreview(null);
          setConfirmed(false);
        }
      }}
    >
      <Dialog.Trigger asChild>
        <Button variant="outline" size="sm" disabled={user?.role === "viewer"}>
          <Upload size={13} />
          {t("Upload data")}
        </Button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content">
          <LanguageSwitcher />
          <Dialog.Title>{t("Bring your orders into focus.")}</Dialog.Title>
          <Dialog.Description>
            {t(
              "Upload a UTF-8 CSV or Excel workbook. Invalid rows remain reviewable; your file is saved only in this local workspace.",
            )}
          </Dialog.Description>
          <Dialog.Close className="dialog-close" aria-label={t("Close upload")}>
            <X size={18} />
          </Dialog.Close>
          <form onSubmit={upload}>
            <div className="dropzone">
              <Upload size={26} />
              <label htmlFor="shipment-file">
                {t("Choose a shipment file")}
                <br />
                <span className="muted">
                  {t(".csv or .xlsx · up to 20 MB")}
                </span>
              </label>
              <input
                id="shipment-file"
                type="file"
                accept=".csv,.xlsx"
                onChange={(event) => {
                  setFile(event.target.files?.[0] ?? null);
                  setPreview(null);
                  setConfirmed(false);
                }}
              />
            </div>
            <Field label={t("Analysis date (UTC)")}>
              <input
                className="input"
                type="date"
                required
                value={date}
                onChange={(e) => {
                  setDate(e.target.value);
                  setPreview(null);
                  setConfirmed(false);
                }}
              />
            </Field>
            <p className="muted small">
              {t(
                "Required: shipment_id, origin, destination, transport_mode, carrier, planned_delivery, actual_delivery, shipping_cost, status.",
              )}
            </p>
            {error && (
              <p className="inline-error" role="alert">
                {t(error)}
              </p>
            )}
            {preview && (
              <div className="import-preview" aria-label={t("Import preview")}>
                <h3>{t("Review the import contract")}</h3>
                {Object.entries(preview.rules)
                  .filter(([name]) => name !== "version")
                  .map(([name, value]) => (
                    <p key={name}>
                      <strong>{t(name)}:</strong> {t(value)}
                    </p>
                  ))}
                <p>
                  {t(preview.kpis.total_shipments)}{" "}
                  {t(" retained shipments · ")}
                  {t(preview.kpis.cost_eligible_shipments)} {t(" USD costs · ")}
                  {t(preview.issue_count)} {t(" quality findings · ")}
                  {t(preview.duplicate_rows)} {t(" duplicate source rows.")}
                </p>
                <details>
                  <summary>
                    {t("Date precision, conflicts and quality preview")}
                  </summary>
                  <pre>
                    {JSON.stringify(
                      {
                        date_precision: preview.date_precision,
                        sample: preview.sample,
                        duplicates: preview.conflict_preview,
                        issues: preview.issues,
                      },
                      null,
                      2,
                    )}
                  </pre>
                </details>
                <label className="checkbox-field">
                  <input
                    type="checkbox"
                    checked={confirmed}
                    onChange={(e) => setConfirmed(e.target.checked)}
                  />
                  {t(
                    "I confirm UTC/midnight deadlines, first-occurrence duplicates and USD cost rules for this file.",
                  )}
                </label>
              </div>
            )}
            <div className="toolbar-actions">
              <Button
                type="submit"
                disabled={busy || (!!preview && !confirmed)}
              >
                <BusyLabel busy={busy}>
                  {t(preview ? "Confirm import" : "Preview import")}
                </BusyLabel>
              </Button>
              <Button asChild variant="ghost">
                <a href="/api/demo/csv" download>
                  {t("Download demo CSV")}
                </a>
              </Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function Shell({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const user = useAccess();
  const path = usePathname();
  const title =
    [...navigation].reverse().find((item) => path.startsWith(item.href))
      ?.label ?? "Overview";
  const { data, datasets, datasetId, selectDataset, asOf, setAsOf } =
    useWorkspace();
  const [mobileOpen, setMobileOpen] = useState(false);
  return (
    <div className="app-frame">
      <aside className="app-sidebar">
        <Brand />
        <Navigation />
        <div className="sidebar-bottom">
          <div>
            <span className="live-dot" />
            {t("Local workspace")}
          </div>
          <p>
            {t("Explainable decisions.")}
            <br />
            {t("Human judgment in control.")}
          </p>
          <Link href="/">
            {t("Back to website ")}
            <ArrowUpRight size={12} />
          </Link>
        </div>
      </aside>
      <div className="app-main">
        <header className="app-header">
          <div className="header-location">
            <Dialog.Root open={mobileOpen} onOpenChange={setMobileOpen}>
              <Dialog.Trigger asChild>
                <Button
                  className="mobile-menu-button"
                  size="icon"
                  variant="ghost"
                  aria-label={t("Open navigation")}
                >
                  <Menu size={20} />
                </Button>
              </Dialog.Trigger>
              <Dialog.Portal>
                <Dialog.Overlay className="dialog-overlay" />
                <Dialog.Content className="mobile-drawer">
                  <Dialog.Title className="sr-only">
                    {t("Platform navigation")}
                  </Dialog.Title>
                  <Dialog.Description className="sr-only">
                    {t("Choose a workspace page.")}
                  </Dialog.Description>
                  <Dialog.Close
                    className="dialog-close"
                    aria-label={t("Close navigation")}
                  >
                    <X size={19} />
                  </Dialog.Close>
                  <Brand />
                  <Navigation close={() => setMobileOpen(false)} />
                </Dialog.Content>
              </Dialog.Portal>
            </Dialog.Root>
            <span>{t("Workspace")}</span>
            <ChevronRight size={12} />
            <strong>{t(title)}</strong>
          </div>
          <div className="header-right">
            <LanguageSwitcher />
            <AccountControl />
            <Link
              href="/app/settings"
              aria-label={t("Methodology and settings")}
            >
              <CircleHelp size={16} className="muted" />
            </Link>
            <span className="avatar" aria-label={t("Local workspace")}>
              {t("LI")}
            </span>
          </div>
        </header>
        <main id="main-content" className="app-content">
          {user?.read_only_demo && (
            <div className="notice" role="status">
              {t(
                "Read-only synthetic demo. No real customer data or accounts. Uploads, scenario comparison, settings changes, history edits and online optimization are disabled by the server. The full protected application retains these operations.",
              )}
            </div>
          )}
          <div className="dataset-bar">
            <select
              aria-label={t("Active dataset")}
              className="input dataset-select"
              value={datasetId}
              onChange={(e) => {
                const dataset = datasets.find(
                  (item) => item.dataset_id === e.target.value,
                );
                if (dataset) selectDataset(dataset);
              }}
            >
              <option value="demo">{t("Synthetic Demo Data")}</option>
              {datasets
                .filter((item) => item.dataset_id !== "demo")
                .map((item) => (
                  <option value={item.dataset_id} key={item.dataset_id}>
                    {item.name}
                  </option>
                ))}
            </select>
            <label>
              {t("Analysis date")}
              <input
                aria-label={t("Workspace analysis date")}
                type="date"
                className="input"
                value={asOf}
                onChange={(e) => {
                  if (e.target.value) setAsOf(e.target.value);
                }}
              />
            </label>
            <UploadDialog />
            <Badge tone={data?.dataset.synthetic ? "blue" : "neutral"}>
              {t(
                data?.dataset.synthetic
                  ? "Synthetic Demo Data"
                  : data
                    ? "User upload · provenance unverified"
                    : "Local dataset",
              )}
            </Badge>
          </div>
          {t(children)}
          <footer className="app-footer">
            <span>
              {t(
                "Engineering prototype. Simulated data and assumptions are labeled.",
              )}
            </span>
            <span>{t("No live carrier connections")}</span>
          </footer>
        </main>
      </div>
    </div>
  );
}
export function AppShell({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  return (
    <AccessGate>
      <WorkspaceProvider>
        <Shell>{t(children)}</Shell>
      </WorkspaceProvider>
    </AccessGate>
  );
}

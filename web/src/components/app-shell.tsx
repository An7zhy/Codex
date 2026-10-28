"use client";

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
  const path = usePathname();
  return (
    <>
      <p className="workspace-label">Operations workspace</p>
      <nav className="app-nav" aria-label="Platform navigation">
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
            {item.label}
            {item.label === "Optimization" && (
              <span className="nav-index">V3</span>
            )}
          </Link>
        ))}
      </nav>
    </>
  );
}

function UploadDialog() {
  const user = useAccess();
  const [open, setOpen] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const { asOf, selectDataset, notify } = useWorkspace();
  const [date, setDate] = useState(asOf);
  const [preview, setPreview] = useState<{ confirmation: string; rules: Record<string, string>; kpis: Record<string, number>; issue_count: number; duplicate_rows: number; date_precision: unknown; conflict_preview: unknown; issues: unknown; sample: unknown } | null>(null);
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
        const result = await api<NonNullable<typeof preview>>("/datasets/preview", { method: "POST", body: form });
        setPreview(result); setConfirmed(false);
        return;
      }
      if (!confirmed) { setError("Review and confirm the import rules first."); return; }
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
          setPreview(null); setConfirmed(false);
        }
      }}
    >
      <Dialog.Trigger asChild>
        <Button variant="outline" size="sm" disabled={user?.role === "viewer"}>
          <Upload size={13} />
          Upload data
        </Button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content">
          <Dialog.Title>Bring your orders into focus.</Dialog.Title>
          <Dialog.Description>
            Upload a UTF-8 CSV or Excel workbook. Invalid rows remain
            reviewable; your file is saved only in this local workspace.
          </Dialog.Description>
          <Dialog.Close className="dialog-close" aria-label="Close upload">
            <X size={18} />
          </Dialog.Close>
          <form onSubmit={upload}>
            <div className="dropzone">
              <Upload size={26} />
              <label htmlFor="shipment-file">
                Choose a shipment file
                <br />
                <span className="muted">.csv or .xlsx · up to 20 MB</span>
              </label>
              <input
                id="shipment-file"
                type="file"
                accept=".csv,.xlsx"
                onChange={(event) => { setFile(event.target.files?.[0] ?? null); setPreview(null); setConfirmed(false); }}
              />
            </div>
            <Field label="Analysis date (UTC)">
              <input
                className="input"
                type="date"
                required
                value={date}
                onChange={(e) => { setDate(e.target.value); setPreview(null); setConfirmed(false); }}
              />
            </Field>
            <p className="muted small">
              Required: shipment_id, origin, destination, transport_mode,
              carrier, planned_delivery, actual_delivery, shipping_cost, status.
            </p>
            {error && (
              <p className="inline-error" role="alert">
                {error}
              </p>
            )}
            {preview && <div className="import-preview" aria-label="Import preview">
              <h3>Review the import contract</h3>
              {Object.entries(preview.rules).filter(([name]) => name !== "version").map(([name, value]) => <p key={name}><strong>{name}:</strong> {value}</p>)}
              <p>{preview.kpis.total_shipments} retained shipments · {preview.kpis.cost_eligible_shipments} USD costs · {preview.issue_count} quality findings · {preview.duplicate_rows} duplicate source rows.</p>
              <details><summary>Date precision, conflicts and quality preview</summary><pre>{JSON.stringify({ date_precision: preview.date_precision, sample: preview.sample, duplicates: preview.conflict_preview, issues: preview.issues }, null, 2)}</pre></details>
              <label className="checkbox-field"><input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />I confirm UTC/midnight deadlines, first-occurrence duplicates and USD cost rules for this file.</label>
            </div>}
            <div className="toolbar-actions">
              <Button type="submit" disabled={busy || (!!preview && !confirmed)}>
                <BusyLabel busy={busy}>{preview ? "Confirm import" : "Preview import"}</BusyLabel>
              </Button>
              <Button asChild variant="ghost">
                <a href="/api/demo/csv" download>
                  Download demo CSV
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
            Local workspace
          </div>
          <p>
            Explainable decisions.
            <br />
            Human judgment in control.
          </p>
          <Link href="/">
            Back to website <ArrowUpRight size={12} />
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
                  aria-label="Open navigation"
                >
                  <Menu size={20} />
                </Button>
              </Dialog.Trigger>
              <Dialog.Portal>
                <Dialog.Overlay className="dialog-overlay" />
                <Dialog.Content className="mobile-drawer">
                  <Dialog.Title className="sr-only">
                    Platform navigation
                  </Dialog.Title>
                  <Dialog.Description className="sr-only">
                    Choose a workspace page.
                  </Dialog.Description>
                  <Dialog.Close
                    className="dialog-close"
                    aria-label="Close navigation"
                  >
                    <X size={19} />
                  </Dialog.Close>
                  <Brand />
                  <Navigation close={() => setMobileOpen(false)} />
                </Dialog.Content>
              </Dialog.Portal>
            </Dialog.Root>
            <span>Workspace</span>
            <ChevronRight size={12} />
            <strong>{title}</strong>
          </div>
          <div className="header-right">
            <AccountControl />
            <Link href="/app/settings" aria-label="Methodology and settings">
              <CircleHelp size={16} className="muted" />
            </Link>
            <span className="avatar" aria-label="Local workspace">
              LI
            </span>
          </div>
        </header>
        <main id="main-content" className="app-content">
          <div className="dataset-bar">
            <select
              aria-label="Active dataset"
              className="input dataset-select"
              value={datasetId}
              onChange={(e) => {
                const dataset = datasets.find(
                  (item) => item.dataset_id === e.target.value,
                );
                if (dataset) selectDataset(dataset);
              }}
            >
              <option value="demo">Synthetic Demo Data</option>
              {datasets
                .filter((item) => item.dataset_id !== "demo")
                .map((item) => (
                  <option value={item.dataset_id} key={item.dataset_id}>
                    {item.name}
                  </option>
                ))}
            </select>
            <label>
              Analysis date
              <input
                aria-label="Workspace analysis date"
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
              {data?.dataset.synthetic
                ? "Synthetic Demo Data"
                : data
                  ? "User upload · provenance unverified"
                  : "Local dataset"}
            </Badge>
          </div>
          {children}
          <footer className="app-footer">
            <span>
              Engineering prototype. Simulated data and assumptions are labeled.
            </span>
            <span>No live carrier connections</span>
          </footer>
        </main>
      </div>
    </div>
  );
}
export function AppShell({ children }: { children: ReactNode }) {
  return (
    <AccessGate>
    <WorkspaceProvider>
      <Shell>{children}</Shell>
    </WorkspaceProvider>
    </AccessGate>
  );
}

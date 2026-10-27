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
  const [open, setOpen] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const { asOf, selectDataset, notify } = useWorkspace();
  const [date, setDate] = useState(asOf);
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
        }
      }}
    >
      <Dialog.Trigger asChild>
        <Button variant="outline" size="sm">
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
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              />
            </div>
            <Field label="Analysis date (UTC)">
              <input
                className="input"
                type="date"
                required
                value={date}
                onChange={(e) => setDate(e.target.value)}
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
            <div className="toolbar-actions">
              <Button type="submit" disabled={busy}>
                <BusyLabel busy={busy}>Upload and analyze</BusyLabel>
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
            <span>Logistics decision copilot</span>
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
    <WorkspaceProvider>
      <Shell>{children}</Shell>
    </WorkspaceProvider>
  );
}

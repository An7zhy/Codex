"use client";
import { useI18n } from "@/lib/i18n/provider";

import {
  cloneElement,
  isValidElement,
  useId,
  type ReactElement,
  type ReactNode,
} from "react";
import { AlertTriangle, ArrowUpRight, Inbox, LoaderCircle } from "lucide-react";
import { cn } from "@/lib/utils";

export function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: string;
}) {
  const { t } = useI18n();
  return <span className={cn("badge", `badge-${tone}`)}>{t(children)}</span>;
}
export function StatusBadge({ value }: { value: string }) {
  const { t } = useI18n();
  const tone = ["OPTIMAL", "Delivered", "Resolved", "Low"].includes(value)
    ? "green"
    : ["INFEASIBLE", "High", "Delayed delivery"].includes(value)
      ? "red"
      : [
            "FEASIBLE",
            "In Transit",
            "Medium",
            "In Progress",
            "Overdue in transit",
          ].includes(value)
        ? "amber"
        : "neutral";
  return <Badge tone={tone}>{t(value)}</Badge>;
}
export function Panel({
  title,
  subtitle,
  action,
  children,
  className = "",
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  const { t } = useI18n();
  return (
    <section className={cn("panel", className)}>
      <header className="panel-head">
        <div>
          <h2>{t(title)}</h2>
          {subtitle && <p>{t(subtitle)}</p>}
        </div>
        {t(action)}
      </header>
      {t(children)}
    </section>
  );
}
export function PageHeading({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  const { t } = useI18n();
  return (
    <div className="page-heading">
      <div>
        <h1>{t(title)}</h1>
        <p>{t(description)}</p>
      </div>
      <div className="heading-actions">{t(action)}</div>
    </div>
  );
}
export function EmptyState({
  title,
  text,
  action,
}: {
  title: string;
  text: string;
  action?: ReactNode;
}) {
  const { t } = useI18n();
  return (
    <div className="empty-state">
      <Inbox size={30} strokeWidth={1.2} />
      <h3>{t(title)}</h3>
      <p>{t(text)}</p>
      {t(action)}
    </div>
  );
}
export function ErrorState({
  message,
  retry,
}: {
  message: string;
  retry?: () => void;
}) {
  const { t } = useI18n();
  return (
    <div className="error-state" role="alert">
      <AlertTriangle size={20} />
      <div>
        <strong>{t("Unable to complete this request")}</strong>
        <p>{t(message)}</p>
        {retry && (
          <button className="text-button" onClick={retry}>
            {t("Try again ")}
            <ArrowUpRight size={13} />
          </button>
        )}
      </div>
    </div>
  );
}
export function LoadingState() {
  const { t } = useI18n();
  return (
    <div
      className="loading-layout"
      aria-busy="true"
      aria-label={t("Loading calculated results")}
    >
      <div className="skeleton skeleton-title" />
      <div className="skeleton-kpis">
        {[0, 1, 2, 3].map((i) => (
          <div className="skeleton" key={i} />
        ))}
      </div>
      <div className="skeleton skeleton-chart" />
      <div className="skeleton skeleton-chart" />
    </div>
  );
}
export function BusyLabel({
  busy,
  children,
}: {
  busy: boolean;
  children: ReactNode;
}) {
  const { t } = useI18n();
  return (
    <>
      {busy && <LoaderCircle size={16} className="spin" />}
      {t(children)}
    </>
  );
}
export function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  const { t } = useI18n();
  const generated = useId();
  const child = isValidElement(children)
    ? (children as ReactElement<{ id?: string; "aria-describedby"?: string }>)
    : null;
  const id = child?.props.id ?? generated;
  const hintId = `${id}-hint`;
  return (
    <div className="field">
      <label htmlFor={id}>{t(label)}</label>
      {child
        ? cloneElement(child, {
            id,
            "aria-describedby":
              [child.props["aria-describedby"], hint ? hintId : ""]
                .filter(Boolean)
                .join(" ") || undefined,
          })
        : children}
      {hint && <small id={hintId}>{t(hint)}</small>}
    </div>
  );
}

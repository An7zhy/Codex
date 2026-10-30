"use client";
import { useI18n } from "@/lib/i18n/provider";
import Link from "next/link";
import { Brand } from "@/components/brand";
export default function NotFound() {
  const { t } = useI18n();
  return (
    <main className="not-found">
      <Brand />
      <h1>{t("This route is off the map.")}</h1>
      <p>
        {t(
          "The page may have moved. Your saved data remains in local storage.",
        )}
      </p>
      <Link className="button button-primary" href="/app">
        {t("Open platform")}
      </Link>
    </main>
  );
}

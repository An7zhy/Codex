"use client";
import { useI18n } from "@/lib/i18n/provider";
import { ErrorState } from "@/components/ui/primitives";
export default function ErrorPage({
  error,
  reset,
}: {
  error: Error;
  reset: () => void;
}) {
  const { t } = useI18n();
  return <ErrorState message={t(error.message)} retry={reset} />;
}

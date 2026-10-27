"use client";
import { ErrorState } from "@/components/ui/primitives";
export default function ErrorPage({
  error,
  reset,
}: {
  error: Error;
  reset: () => void;
}) {
  return <ErrorState message={error.message} retry={reset} />;
}

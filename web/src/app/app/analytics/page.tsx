import { Analytics } from "@/components/analytics";
import { Suspense } from "react";
import { LoadingState } from "@/components/ui/primitives";
export default function AnalyticsPage() {
  return <Suspense fallback={<LoadingState />}><Analytics /></Suspense>;
}

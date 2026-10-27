import { Suspense } from "react";
import { Decisions } from "@/components/decisions";
import { LoadingState } from "@/components/ui/primitives";
export default function DecisionsPage() {
  return (
    <Suspense fallback={<LoadingState />}>
      <Decisions />
    </Suspense>
  );
}

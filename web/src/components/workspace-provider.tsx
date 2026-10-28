"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { CheckCircle2, X } from "lucide-react";
import { api } from "@/lib/utils";
import type { Dataset, Workspace, Shipment } from "@/lib/types";
import { ErrorState, LoadingState } from "@/components/ui/primitives";
import { Button } from "@/components/ui/button";

type Filters = {
  q: string;
  carrier: string;
  mode: string;
  status: string;
  offset: number;
};
const emptyFilters: Filters = {
  q: "",
  carrier: "",
  mode: "",
  status: "",
  offset: 0,
};
type ContextValue = {
  data: Workspace | null;
  loading: boolean;
  error: string;
  datasetId: string;
  datasets: Dataset[];
  asOf: string;
  setAsOf: (value: string) => void;
  filters: Filters;
  setFilter: (key: keyof Filters, value: string | number) => void;
  clearFilters: () => void;
  selectDataset: (dataset: Dataset) => void;
  refresh: () => void;
  query: string;
  notify: (message: string) => void;
};
const Context = createContext<ContextValue | null>(null);

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [datasetId, setDatasetId] = useState("demo");
  const [asOf, setAsOf] = useState("2026-10-01");
  const [filters, setFilters] = useState<Filters>(emptyFilters);
  const [ready, setReady] = useState(false);
  const [revision, setRevision] = useState(0);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [data, setData] = useState<Workspace | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState("");
  useEffect(() => {
    try {
      const saved = JSON.parse(
        localStorage.getItem("logistics-workspace-v1") || "null",
      );
      if (saved?.datasetId && saved?.asOf) {
        setDatasetId(saved.datasetId);
        setAsOf(saved.asOf);
      }
    } catch {
      /* Private browsing can disable storage; the demo still works. */
    }
    setReady(true);
  }, []);
  useEffect(() => {
    if (ready) {
      try {
        localStorage.setItem(
          "logistics-workspace-v1",
          JSON.stringify({ datasetId, asOf }),
        );
      } catch {
        /* session-only fallback */
      }
    }
  }, [datasetId, asOf, ready]);
  const query = useMemo(
    () =>
      new URLSearchParams({
        dataset_id: datasetId,
        as_of: asOf,
        q: filters.q,
        carrier: filters.carrier,
        mode: filters.mode,
        status: filters.status,
        offset: String(filters.offset),
        limit: "20",
      }).toString(),
    [datasetId, asOf, filters],
  );
  useEffect(() => {
    if (!ready) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setLoading(true);
      setError("");
      api<Workspace>(`/workspace?${query}`, { signal: controller.signal })
        .then(setData)
        .catch((err) => {
          if (err.name !== "AbortError") setError(err.message);
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }, 130);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [query, revision, ready]);
  useEffect(() => {
    const controller = new AbortController();
    api<Dataset[]>("/datasets", { signal: controller.signal })
      .then(setDatasets)
      .catch(() => {});
    return () => controller.abort();
  }, [revision]);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 5000);
    return () => clearTimeout(timer);
  }, [toast]);
  const refresh = useCallback(() => setRevision((v) => v + 1), []);
  const selectDataset = useCallback(
    (dataset: Dataset) => {
      setDatasetId(dataset.dataset_id);
      setAsOf(dataset.as_of);
      setFilters(emptyFilters);
      refresh();
    },
    [refresh],
  );
  const setFilter = useCallback(
    (key: keyof Filters, value: string | number) =>
      setFilters((old) => ({
        ...old,
        [key]: value,
        ...(key !== "offset" ? { offset: 0 } : {}),
      })),
    [],
  );
  return (
    <Context.Provider
      value={{
        data,
        loading,
        error,
        datasetId,
        datasets,
        asOf,
        setAsOf,
        filters,
        setFilter,
        clearFilters: () => setFilters(emptyFilters),
        selectDataset,
        refresh,
        query,
        notify: setToast,
      }}
    >
      {children}
      {toast && (
        <div className="toast" role="status">
          <CheckCircle2 size={18} />
          <span>{toast}</span>
          <button
            aria-label="Dismiss notification"
            onClick={() => setToast("")}
          >
            <X size={15} />
          </button>
        </div>
      )}
    </Context.Provider>
  );
}
export function useWorkspace() {
  const context = useContext(Context);
  if (!context) throw new Error("Workspace provider is required.");
  return context;
}
export function useExceptionQueue(page: number, actionable = false, search = "", limit = 20) {
  const { query, data } = useWorkspace();
  const [queue, setQueue] = useState<{ items: Shipment[]; total: number }>({ items: [], total: 0 });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams(query);
    params.set("offset", String(page * limit)); params.set("limit", String(limit));
    params.set("actionable_only", String(actionable));
    if (search) params.set("q", search);
    setLoading(true); setError("");
    api<typeof queue>(`/exceptions?${params}`, { signal: controller.signal }).then(setQueue)
      .catch((err) => { if (err.name !== "AbortError") setError(err.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [query, page, actionable, search, limit, data]); // refreshed settings also refresh the queue
  return { ...queue, error, loading };
}
export function WorkspaceBoundary({ children }: { children: ReactNode }) {
  const { loading, error, data, refresh, datasets, selectDataset } =
    useWorkspace();
  if (error)
    return (
      <>
        <ErrorState message={error} retry={refresh} />
        {error.startsWith("Dataset not found") && (
          <Button
            variant="outline"
            onClick={() =>
              selectDataset(
                datasets.find((item) => item.dataset_id === "demo") ?? {
                  dataset_id: "demo",
                  name: "Synthetic Demo Data",
                  synthetic: true,
                  as_of: "2026-10-01",
                  created_at: "",
                },
              )
            }
          >
            Use Synthetic Demo Data
          </Button>
        )}
      </>
    );
  if (loading || !data) return <LoadingState />;
  return children;
}

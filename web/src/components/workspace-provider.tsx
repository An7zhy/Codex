"use client";
import { useI18n } from "@/lib/i18n/provider";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { CheckCircle2, X } from "lucide-react";
import { api } from "@/lib/utils";
import type { Dataset, Workspace, Shipment } from "@/lib/types";
import { ErrorState, LoadingState } from "@/components/ui/primitives";
import { Button } from "@/components/ui/button";
import { useAccess } from "@/components/access";

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
  const { t } = useI18n();
  const user = useAccess();
  const storageKey = `logistics-workspace-v2:${user?.instance_id}:${user?.username}`;
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
        localStorage.getItem(storageKey) ||
          localStorage.getItem("logistics-workspace-v1") ||
          "null",
      );
      if (saved?.datasetId && saved?.asOf) {
        setDatasetId(saved.datasetId);
        setAsOf(saved.asOf);
        if (saved.filters && typeof saved.filters === "object") {
          setFilters({
            ...emptyFilters,
            ...Object.fromEntries(
              Object.entries(saved.filters).filter(
                ([key, value]) =>
                  key in emptyFilters &&
                  (key === "offset"
                    ? Number.isInteger(value) && Number(value) >= 0
                    : typeof value === "string"),
              ),
            ),
          });
        }
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
          storageKey,
          JSON.stringify({ datasetId, asOf, filters }),
        );
      } catch {
        /* session-only fallback */
      }
    }
  }, [datasetId, asOf, filters, ready, storageKey]);
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
    setLoading(true);
    setError("");
    let recoveringPage = false;
    const timer = setTimeout(() => {
      api<Workspace>(`/workspace?${query}`, { signal: controller.signal })
        .then((result) => {
          if (controller.signal.aborted) return;
          if (result.offset > 0 && result.offset >= result.total_rows) {
            recoveringPage = true;
            setFilters((old) => ({ ...old, offset: 0 }));
            return;
          }
          setData(result);
        })
        .catch((err) => {
          if (err.name !== "AbortError") setError(err.message);
        })
        .finally(() => {
          if (!controller.signal.aborted && !recoveringPage) setLoading(false);
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
      {t(children)}
      {toast && (
        <div className="toast" role="status">
          <CheckCircle2 size={18} />
          <span>{t(toast)}</span>
          <button
            aria-label={t("Dismiss notification")}
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
export type ExceptionSummary = {
  records: number;
  active: number;
  high: number;
  needs_evidence: number;
  review_only: number;
};
export function filterScopeKey(query: string) {
  const params = new URLSearchParams(query);
  params.delete("offset");
  params.delete("limit");
  params.sort();
  return params.toString();
}
export function useExceptionQueue(
  page: number,
  actionable = false,
  search = "",
  limit = 20,
  setPage?: (page: number) => void,
  resetOnScopeChange = true,
) {
  const { query, data } = useWorkspace();
  const scope = filterScopeKey(query);
  const previousScope = useRef(scope + ":" + search);
  const changedScope = previousScope.current !== scope + ":" + search;
  const requestedPage = changedScope && resetOnScopeChange ? 0 : page;
  const params = new URLSearchParams(scope);
  params.set("offset", String(requestedPage * limit));
  params.set("limit", String(limit));
  params.set("actionable_only", String(actionable));
  if (search) params.set("search", search);
  const requestQuery = params.toString();
  const key = requestQuery + JSON.stringify(data?.priority_config ?? null);
  type Result = {
    items: Shipment[];
    total: number;
    dataset_exception_count: number;
    summary: ExceptionSummary;
  };
  const [state, setState] = useState<{ key: string; result: Result } | null>(
    null,
  );
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (changedScope) {
      previousScope.current = scope + ":" + search;
      if (resetOnScopeChange) setPage?.(0);
    }
  }, [scope, search, changedScope, setPage, resetOnScopeChange]);
  useEffect(() => {
    const controller = new AbortController();
    setBusy(true);
    setError("");
    api<Result>(`/exceptions?${requestQuery}`, { signal: controller.signal })
      .then((result) => {
        if (controller.signal.aborted) return;
        if (
          requestedPage > 0 &&
          requestedPage * limit >= result.total &&
          setPage
        ) {
          setPage(0);
          return;
        }
        setState({ key, result });
      })
      .catch((err) => {
        if (err.name !== "AbortError") {
          setError(err.message);
          setState(null);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setBusy(false);
      });
    return () => controller.abort();
  }, [requestQuery, key, data]);
  const result = state?.key === key ? state.result : null;
  return {
    items: result?.items ?? [],
    total: result?.total ?? 0,
    datasetTotal: result?.dataset_exception_count ?? 0,
    summary: result?.summary,
    page: requestedPage,
    pageCount: Math.max(1, Math.ceil((result?.total ?? 0) / limit)),
    error,
    loading: busy || (!result && !error),
  };
}
export function WorkspaceBoundary({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const { loading, error, data, refresh, datasets, selectDataset } =
    useWorkspace();
  if (error)
    return (
      <>
        <ErrorState message={t(error)} retry={refresh} />
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
            {t("Use Synthetic Demo Data")}
          </Button>
        )}
      </>
    );
  if (loading || !data) return <LoadingState />;
  return children;
}

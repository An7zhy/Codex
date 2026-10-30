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
import {
  translate,
  translateExact,
  type Locale,
  type Translator,
} from "./translate";

export const LANGUAGE_KEY = "logistics-language";
const I18n = createContext<{
  locale: Locale;
  t: Translator;
  tExact: (value: string) => string;
  setLocale: (locale: Locale) => void;
} | null>(null);

/** Display-only state: switching never remounts the workspace or changes API inputs. */
export function I18nProvider({
  children,
  initialLocale = "zh",
}: {
  children: ReactNode;
  initialLocale?: Locale;
}) {
  const [locale, updateLocale] = useState<Locale>(initialLocale);
  const setLocale = useCallback((next: Locale) => {
    if (next !== "zh" && next !== "en") return;
    updateLocale(next);
    try {
      localStorage.setItem(LANGUAGE_KEY, next);
    } catch {
      /* memory/cookie fallback */
    }
    try {
      document.cookie = `${LANGUAGE_KEY}=${next}; Path=/; Max-Age=31536000; SameSite=Lax${location.protocol === "https:" ? "; Secure" : ""}`;
    } catch {
      /* switching remains usable when cookies are blocked */
    }
  }, []);
  useEffect(() => {
    const sync = (event: StorageEvent) => {
      if (
        event.key === LANGUAGE_KEY &&
        (event.newValue === "zh" || event.newValue === "en")
      )
        setLocale(event.newValue);
    };
    window.addEventListener("storage", sync);
    return () => window.removeEventListener("storage", sync);
  }, [setLocale]);
  useEffect(() => {
    document.documentElement.lang = locale === "zh" ? "zh-CN" : "en";
    document.title = translate(
      locale,
      "Logistics Insight AI — Intelligence behind every shipment",
    );
  }, [locale]);
  const t: Translator = useCallback(
    (value, params) => translate(locale, value, params),
    [locale],
  );
  const tExact = useCallback(
    (value: string) => translateExact(locale, value),
    [locale],
  );
  const context = useMemo(
    () => ({ locale, t, tExact, setLocale }),
    [locale, t, tExact, setLocale],
  );
  return <I18n.Provider value={context}>{children}</I18n.Provider>;
}
export function useI18n() {
  const context = useContext(I18n);
  if (!context) throw new Error("I18nProvider is required");
  return context;
}
export function LanguageSwitcher() {
  const { locale, setLocale } = useI18n();
  return (
    <div
      className="language-switcher"
      role="group"
      aria-label="语言 / Language"
      translate="no"
    >
      <button
        type="button"
        aria-label="中文"
        aria-pressed={locale === "zh"}
        onClick={() => setLocale("zh")}
      >
        中文
      </button>
      <span aria-hidden="true">/</span>
      <button
        type="button"
        aria-label="English"
        aria-pressed={locale === "en"}
        onClick={() => setLocale("en")}
      >
        EN
      </button>
    </div>
  );
}
export function SkipLink() {
  const { t } = useI18n();
  return (
    <a href="#main-content" className="skip-link">
      {t("Skip to content")}
    </a>
  );
}

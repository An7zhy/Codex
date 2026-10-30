import { cookies } from "next/headers";
import { I18nProvider, SkipLink } from "@/lib/i18n/provider";
import { translate } from "@/lib/i18n/translate";
import type { Metadata } from "next";
import "@fontsource-variable/manrope";
import "./globals.css";

export async function generateMetadata(): Promise<Metadata> {
  const locale =
    (await cookies()).get("logistics-language")?.value === "en" ? "en" : "zh";
  return {
    title: {
      default: translate(
        locale,
        "Logistics Insight AI — Intelligence behind every shipment",
      ),
      template: "%s | Logistics Insight AI",
    },
    other: { google: "notranslate" },
    description: translate(
      locale,
      "Explainable logistics exception analysis and transportation optimization. An independent synthetic-data engineering prototype.",
    ),
  };
}
export default async function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const locale =
    (await cookies()).get("logistics-language")?.value === "en" ? "en" : "zh";
  return (
    <html
      lang={locale === "zh" ? "zh-CN" : "en"}
      translate="no"
      className="notranslate"
    >
      <body>
        <I18nProvider initialLocale={locale}>
          <SkipLink />
          {children}
        </I18nProvider>
      </body>
    </html>
  );
}

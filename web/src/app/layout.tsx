import type { Metadata } from "next";
import "@fontsource-variable/manrope";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "Logistics Insight AI — Intelligence behind every shipment",
    template: "%s | Logistics Insight AI",
  },
  description:
    "Explainable logistics exception analysis and transportation optimization. An independent synthetic-data engineering prototype.",
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <a href="#main-content" className="skip-link">
          Skip to content
        </a>
        {children}
      </body>
    </html>
  );
}

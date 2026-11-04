import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { cookies } from "next/headers";
import { InstallableApp } from "@/features/shell/installable-app";
import { parseTheme, themeCookie } from "@/features/theme/theme";
import "./globals.css";

// Fonts are downloaded at build time and served by the app itself: no request
// to Google from the owner's browser.
const body = Geist({
  subsets: ["latin"],
  variable: "--font-body",
});

const code = Geist_Mono({
  subsets: ["latin"],
  variable: "--font-code",
});

export const metadata: Metadata = {
  title: { default: "AGOS", template: "%s · AGOS" },
  description: "Personal agent workspace",
  // Private app: never indexed, even if a URL leaks.
  robots: { index: false, follow: false },
  // Installed on a phone: full screen, no browser bars (iOS reads these;
  // Android reads the manifest).
  appleWebApp: { capable: true, title: "AGOS", statusBarStyle: "default" },
  formatDetection: { telephone: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  // Status bar colour of the installed app, matching the page background.
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#fafafa" },
    { media: "(prefers-color-scheme: dark)", color: "#0a0a0a" },
  ],
};

export default async function RootLayout({ children }: LayoutProps<"/">) {
  const theme = parseTheme((await cookies()).get(themeCookie)?.value);
  return (
    <html
      lang="en"
      data-theme={theme === "system" ? undefined : theme}
      className={`${body.variable} ${code.variable} h-full`}
    >
      <body className="min-h-full">
        {children}
        <InstallableApp />
      </body>
    </html>
  );
}

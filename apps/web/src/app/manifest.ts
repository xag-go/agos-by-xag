import type { MetadataRoute } from "next";

/** "Add to home screen" on a phone or "Install app" in the browser. */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "AGOS",
    short_name: "AGOS",
    description: "Personal agent workspace",
    id: "/",
    scope: "/",
    start_url: "/",
    display: "standalone",
    background_color: "#fafafa",
    theme_color: "#fafafa",
    icons: [
      { src: "/icons/agos-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icons/agos-512.png", sizes: "512x512", type: "image/png" },
      {
        src: "/icons/agos-maskable-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      },
    ],
  };
}

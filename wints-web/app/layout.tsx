import type { Metadata } from "next";
import { Outfit } from "next/font/google";
import "./globals.css";

const outfit = Outfit({
    subsets: ["latin"],
    weight: ["300", "400", "500", "600", "700", "800"],
});

export const metadata: Metadata = {
    title: "⚡ WINTS Control Room — Space-Age Telemetry Dashboard",
    description:
        "Wireless Integrated Network Target System — real-time military grade telemetry & remote control dashboard for 10 motorised range targets.",
    keywords: ["WINTS", "MQTT", "control room", "embedded systems", "real-time", "military range"],
    authors: [{ name: "Hamza Basharat" }],
    openGraph: {
        title: "WINTS Control Room — Space-Age Telemetry",
        description: "Physics-accurate distributed embedded range simulation",
        type: "website",
    },
};

export default function RootLayout({
    children,
}: {
    children: React.ReactNode;
}) {
    return (
        <html lang="en" className="dark">
            <body className={`${outfit.className} bg-base text-text antialiased`}>{children}</body>
        </html>
    );
}

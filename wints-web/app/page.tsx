"use client";
import BrokerConnect from "@/components/BrokerConnect";
import ConnectionBar from "@/components/ConnectionBar";
import EventLog from "@/components/EventLog";
import MetricsPanel from "@/components/MetricsPanel";
import TargetCard from "@/components/TargetCard";
import { store } from "@/lib/mqttStore";
import { useStore } from "@/lib/useStore";
import { ChevronDown, ChevronUp, Square } from "lucide-react";
import { useEffect } from "react";

const TARGET_IDS = Array.from({ length: 10 }, (_, i) => `T-${String(i + 1).padStart(2, "0")}`);

export default function Home() {
    useStore(); // subscribe to global store

    // Auto-connect from env vars on mount
    useEffect(() => {
        const host = process.env.NEXT_PUBLIC_MQTT_HOST;
        const port = parseInt(process.env.NEXT_PUBLIC_MQTT_PORT ?? "8884");
        const user = process.env.NEXT_PUBLIC_MQTT_USERNAME;
        const pass = process.env.NEXT_PUBLIC_MQTT_PASSWORD;
        if (host && user && pass && store.connection === "disconnected") {
            store.connect(host, port, user, pass);
        }
        return () => { /* keep connected on nav */ };
    }, []);

    return (
        <div className="flex flex-col min-h-screen bg-base tech-grid text-text selection:bg-blue/25">

            {/* ── Top bar ── */}
            <header className="glass-panel border-b border-surface0/60 px-4 py-3 sticky top-0 z-40 shadow-xl">
                <div className="flex items-center justify-between flex-wrap gap-3">
                    {/* Logo */}
                    <div className="flex items-center gap-3">
                        <span className="text-xl mono font-black text-blue tracking-tight select-none drop-shadow-[0_0_8px_rgba(137,180,250,0.3)]">⚡ WINTS</span>
                        <span className="text-[10px] uppercase tracking-widest text-overlay hidden sm:block border-l border-surface0 pl-3">Control Room</span>
                    </div>

                    {/* Broadcast commands */}
                    <div className="flex items-center gap-2">
                        <span className="text-[10px] text-overlay font-bold mono hidden sm:block">BROADCAST:</span>
                        <button
                            onClick={() => store.publishCommand("broadcast", "raise")}
                            className="flex items-center gap-1.5 px-3.5 py-1.5 bg-green/10 hover:bg-green/20 hover:shadow-[0_0_12px_rgba(166,227,161,0.25)] text-green border border-green/35 rounded-lg text-xs mono font-bold transition-all active:scale-95 hover:-translate-y-0.5"
                        >
                            <ChevronUp size={12} className="animate-bounce" /> RAISE ALL
                        </button>
                        <button
                            onClick={() => store.publishCommand("broadcast", "stop")}
                            className="flex items-center gap-1.5 px-3.5 py-1.5 bg-yellow/10 hover:bg-yellow/20 hover:shadow-[0_0_12px_rgba(249,226,175,0.25)] text-yellow border border-yellow/35 rounded-lg text-xs mono font-bold transition-all active:scale-95 hover:-translate-y-0.5"
                        >
                            <Square size={10} /> STOP ALL
                        </button>
                        <button
                            onClick={() => store.publishCommand("broadcast", "lower")}
                            className="flex items-center gap-1.5 px-3.5 py-1.5 bg-blue/10 hover:bg-blue/20 hover:shadow-[0_0_12px_rgba(137,180,250,0.25)] text-blue border border-blue/35 rounded-lg text-xs mono font-bold transition-all active:scale-95 hover:-translate-y-0.5"
                        >
                            <ChevronDown size={12} className="animate-bounce" /> LOWER ALL
                        </button>
                    </div>

                    {/* Broker config */}
                    <BrokerConnect />
                </div>
            </header>

            {/* ── Connection bar ── */}
            <ConnectionBar
                state={store.connection}
                onlineCount={store.getOnlineCount()}
                faultCount={store.getFaultCount()}
            />

            {/* ── Main body ── */}
            <div className="flex flex-1 overflow-hidden">

                {/* Target card grid */}
                <main className="flex-1 overflow-y-auto p-4">
                    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
                        {TARGET_IDS.map((id) => (
                            <TargetCard key={id} target={store.targets[id]} />
                        ))}
                    </div>
                </main>

                {/* Right panel — metrics + event log */}
                <aside className="hidden lg:flex flex-col w-56 border-l border-surface0 overflow-hidden">
                    <MetricsPanel />
                    <div className="flex-1 overflow-hidden border-t border-surface0 flex flex-col">
                        <EventLog />
                    </div>
                </aside>
            </div>

            {/* ── Mobile event log (bottom) ── */}
            <div className="lg:hidden border-t border-surface0 h-36 overflow-hidden flex flex-col">
                <EventLog />
            </div>

        </div>
    );
}

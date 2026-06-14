"use client";
import BrokerConnect from "@/components/BrokerConnect";
import ConnectionBar from "@/components/ConnectionBar";
import EventLog from "@/components/EventLog";
import MetricsPanel from "@/components/MetricsPanel";
import TargetCard from "@/components/TargetCard";
import { store } from "@/lib/mqttStore";
import { useStore } from "@/lib/useStore";
import { Activity, ChevronDown, ChevronUp, Clock3, ShieldCheck, Sparkles, Square, Wifi } from "lucide-react";
import { useEffect } from "react";

const TARGET_IDS = Array.from({ length: 10 }, (_, i) => `T-${String(i + 1).padStart(2, "0")}`);

const isPlaceholderValue = (value?: string): boolean => {
    const v = (value ?? "").trim().toLowerCase();
    return (
        !v ||
        v.includes("your_cluster") ||
        v.includes("your-broker") ||
        v.includes("placeholder") ||
        v.includes("example")
    );
};

const envHost = process.env.NEXT_PUBLIC_MQTT_HOST;
const envPort = process.env.NEXT_PUBLIC_MQTT_PORT;
const envUser = process.env.NEXT_PUBLIC_MQTT_USERNAME;
const envPass = process.env.NEXT_PUBLIC_MQTT_PASSWORD;

const brokerConfigured =
    !isPlaceholderValue(envHost) &&
    !isPlaceholderValue(envPort) &&
    !isPlaceholderValue(envUser) &&
    !isPlaceholderValue(envPass);

const STATUS_COPY: Record<string, { label: string; accent: string; detail: string }> = {
    connected: { label: "Connected", accent: "text-green", detail: "Commands are live." },
    connecting: { label: "Connecting", accent: "text-yellow", detail: "Negotiating broker session." },
    disconnected: { label: "Offline", accent: "text-overlay", detail: "Broker disconnected." },
    error: { label: "Error", accent: "text-red", detail: "Check MQTT credentials." },
};

export default function Home() {
    useStore();
    const status = brokerConfigured
        ? STATUS_COPY[store.connection]
        : { label: "Setup required", accent: "text-yellow", detail: "Add MQTT broker variables in Vercel." };
    const onlineCount = store.getOnlineCount();
    const faultCount = store.getFaultCount();
    const latestError = store.events.find((e) => e.type === "error")?.message;

    useEffect(() => {
        const host = envHost;
        const port = parseInt(envPort ?? "8884", 10);
        const user = envUser;
        const pass = envPass;
        if (host && user && pass && store.connection === "disconnected") {
            store.connect(host, port, user, pass);
        }
        return () => {};
    }, []);

    return (
        <div className="flex min-h-screen flex-col bg-base text-text selection:bg-blue/25 tech-grid">
            <header className="glass-panel sticky top-0 z-40 border-b border-surface0/60 px-4 py-3 shadow-xl">
                <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex items-center gap-3">
                        <span className="select-none text-xl font-black tracking-tight text-blue mono drop-shadow-[0_0_8px_rgba(137,180,250,0.3)]">WINTS</span>
                        <span className="hidden border-l border-surface0 pl-3 text-[10px] font-bold uppercase tracking-widest text-overlay sm:block">
                            Control Room
                        </span>
                    </div>

                    <div className="flex flex-wrap items-center justify-center gap-2 sm:justify-end">
                        <span className="hidden text-[10px] font-bold text-overlay mono sm:block">BROADCAST:</span>
                        <button
                            onClick={() => store.publishCommand("broadcast", "raise")}
                            aria-label="Raise all targets"
                            className="flex items-center gap-1.5 rounded-lg border border-green/35 bg-green/10 px-3.5 py-1.5 text-xs font-bold text-green mono transition-all hover:-translate-y-0.5 hover:bg-green/20 hover:shadow-[0_0_12px_rgba(166,227,161,0.25)] active:scale-95"
                        >
                            <ChevronUp size={12} className="animate-bounce" /> RAISE ALL
                        </button>
                        <button
                            onClick={() => store.publishCommand("broadcast", "stop")}
                            aria-label="Stop all targets"
                            className="flex items-center gap-1.5 rounded-lg border border-yellow/35 bg-yellow/10 px-3.5 py-1.5 text-xs font-bold text-yellow mono transition-all hover:-translate-y-0.5 hover:bg-yellow/20 hover:shadow-[0_0_12px_rgba(249,226,175,0.25)] active:scale-95"
                        >
                            <Square size={10} /> STOP ALL
                        </button>
                        <button
                            onClick={() => store.publishCommand("broadcast", "lower")}
                            aria-label="Lower all targets"
                            className="flex items-center gap-1.5 rounded-lg border border-blue/35 bg-blue/10 px-3.5 py-1.5 text-xs font-bold text-blue mono transition-all hover:-translate-y-0.5 hover:bg-blue/20 hover:shadow-[0_0_12px_rgba(137,180,250,0.25)] active:scale-95"
                        >
                            <ChevronDown size={12} className="animate-bounce" /> LOWER ALL
                        </button>
                    </div>

                    <BrokerConnect defaultOpen={!brokerConfigured} />
                </div>
            </header>

            <ConnectionBar state={store.connection} onlineCount={onlineCount} faultCount={faultCount} />

            <section className="px-4 pt-4">
                <div className="grid gap-3 lg:grid-cols-[1.3fr_1fr_1fr]">
                    <div className="glass-card rounded-2xl border border-surface0/50 p-4 shadow-lg">
                        <div className="flex items-start justify-between gap-3">
                            <div className="space-y-2">
                                <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.25em] text-overlay mono">
                                    <Sparkles size={12} className="text-blue" />
                                    Live cockpit
                                </div>
                                <h1 className="text-lg font-black tracking-tight text-text sm:text-xl">
                                    WINTS Control Room
                                </h1>
                                <p className="max-w-2xl text-sm leading-relaxed text-overlay">
                                    Monitor 10 targets, push broadcast commands, and watch telemetry update in real time.
                                    The dashboard is tuned for secure WebSocket MQTT connections, which is exactly what
                                    Vercel likes to see.
                                </p>
                            </div>
                            <div className="hidden h-12 w-12 items-center justify-center rounded-2xl border border-blue/25 bg-blue/10 text-blue shadow-[0_0_16px_rgba(137,180,250,0.16)] sm:flex">
                                <Activity size={22} />
                            </div>
                        </div>
                    </div>

                    <div className="glass-card rounded-2xl border border-surface0/50 p-4 shadow-lg">
                        <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.25em] text-overlay mono">
                            <Clock3 size={12} className="text-yellow" />
                            System status
                        </div>
                        <div className="mt-3 flex items-end justify-between gap-3">
                            <div>
                                <div className={`text-2xl font-black ${status.accent}`}>{status.label}</div>
                                <div className="mt-1 text-sm text-overlay">{status.detail}</div>
                            </div>
                            <div className="rounded-xl border border-surface0/45 bg-crust/60 px-3 py-2 text-right">
                                <div className="text-[10px] uppercase tracking-widest text-overlay mono">Online</div>
                                <div className="text-xl font-black text-green mono">{onlineCount}/10</div>
                            </div>
                        </div>
                    </div>

                    <div className="glass-card rounded-2xl border border-surface0/50 p-4 shadow-lg">
                        <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.25em] text-overlay mono">
                            <ShieldCheck size={12} className="text-green" />
                            Deploy note
                        </div>
                        <p className="mt-3 text-sm leading-relaxed text-overlay">
                            Use a secure MQTT WebSocket broker for production. On Vercel, prefer
                            <span className="font-bold text-text mono"> wss://</span> and avoid plain
                            <span className="font-bold text-text mono"> ws://</span> connections.
                        </p>
                        <div className="mt-3 inline-flex items-center gap-2 rounded-full border border-surface0/45 bg-surface0/25 px-3 py-1 text-[10px] text-text mono">
                            <Wifi size={11} className="text-blue" />
                            {faultCount} fault{faultCount === 1 ? "" : "s"} tracked
                        </div>
                    </div>

                    {!brokerConfigured && (
                        <div className="glass-card rounded-2xl border border-yellow/35 bg-yellow/10 p-4 shadow-lg lg:col-span-3">
                            <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                                <div>
                                    <div className="text-[10px] font-bold uppercase tracking-[0.25em] text-yellow mono">
                                        MQTT setup needed
                                    </div>
                                    <h2 className="mt-2 text-lg font-black text-text">
                                        Connect a broker to unlock live telemetry
                                    </h2>
                                    <p className="mt-2 max-w-3xl text-sm leading-relaxed text-overlay">
                                        The dashboard is deployed correctly, but it needs a secure MQTT WebSocket broker
                                        to show live data. Add the Vercel environment variables, then redeploy.
                                    </p>
                                </div>
                                <div className="flex flex-wrap gap-2 text-[10px] text-text mono">
                                    <span className="rounded-full border border-yellow/25 bg-crust/70 px-3 py-1">NEXT_PUBLIC_MQTT_HOST</span>
                                    <span className="rounded-full border border-yellow/25 bg-crust/70 px-3 py-1">NEXT_PUBLIC_MQTT_PORT</span>
                                    <span className="rounded-full border border-yellow/25 bg-crust/70 px-3 py-1">NEXT_PUBLIC_MQTT_USERNAME</span>
                                    <span className="rounded-full border border-yellow/25 bg-crust/70 px-3 py-1">NEXT_PUBLIC_MQTT_PASSWORD</span>
                                </div>
                            </div>
                        </div>
                    )}

                    {brokerConfigured && (store.connection === "disconnected" || store.connection === "error") && (
                        <div className="glass-card rounded-2xl border border-red/35 bg-red/10 p-4 shadow-lg lg:col-span-3">
                            <div className="text-[10px] font-bold uppercase tracking-[0.25em] text-red mono">
                                Connection troubleshooting
                            </div>
                            <h2 className="mt-2 text-lg font-black text-text">
                                Broker values exist, but connection is failing
                            </h2>
                            <p className="mt-2 max-w-3xl text-sm leading-relaxed text-overlay">
                                Verify host, port, username, and password. Host must be only the domain with no
                                protocol or path, and secure WebSocket port is usually
                                <span className="font-bold text-text mono"> 8884</span>.
                            </p>
                            {latestError && (
                                <div className="mt-3 break-all rounded-lg border border-red/30 bg-crust/70 px-3 py-2 text-xs text-red mono">
                                    Last error: {latestError}
                                </div>
                            )}
                        </div>
                    )}
                </div>
            </section>

            <div className="flex flex-1 overflow-hidden pt-4">
                <main className="flex-1 overflow-y-auto px-4 pb-4">
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
                        {TARGET_IDS.map((id) => (
                            <TargetCard key={id} target={store.targets[id]} />
                        ))}
                    </div>
                </main>

                <aside className="sticky top-[110px] hidden max-h-[calc(100vh-110px)] w-72 flex-col overflow-hidden border-l border-surface0 lg:flex">
                    <MetricsPanel />
                    <div className="flex flex-1 flex-col overflow-hidden border-t border-surface0">
                        <EventLog />
                    </div>
                </aside>
            </div>

            <div className="flex h-40 flex-col overflow-hidden border-t border-surface0 lg:hidden">
                <EventLog />
            </div>
        </div>
    );
}

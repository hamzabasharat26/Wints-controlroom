"use client";
import { ConnectionState } from "@/lib/useStore";
import { AlertCircle, Loader2, Wifi, WifiOff } from "lucide-react";

interface Props {
    state: ConnectionState;
    onlineCount: number;
    faultCount: number;
}

const CONFIG = {
    connected: { icon: Wifi, color: "text-green", bg: "bg-green/10", label: "Connected" },
    connecting: { icon: Loader2, color: "text-yellow", bg: "bg-yellow/10", label: "Connecting..." },
    disconnected: { icon: WifiOff, color: "text-overlay", bg: "bg-surface0", label: "Disconnected" },
    error: { icon: AlertCircle, color: "text-red", bg: "bg-red/10", label: "Connection Error" },
} as const;

export default function ConnectionBar({ state, onlineCount, faultCount }: Props) {
    const cfg = CONFIG[state];
    const Icon = cfg.icon;
    const spinning = state === "connecting";

    return (
        <div className={`flex flex-col gap-2 px-4 py-3 border-b border-surface0/70 ${cfg.bg} sm:flex-row sm:items-center sm:justify-between`}>
            {/* Left connection status */}
            <div className={`flex items-center gap-2 text-sm font-medium ${cfg.color}`}>
                <Icon size={15} className={spinning ? "animate-spin" : ""} />
                <span className="mono">{cfg.label}</span>
            </div>

            {/* Center system title */}
            <div className="hidden sm:flex flex-col items-center text-center">
                <span className="mono text-blue font-bold tracking-wider text-sm">
                    WINTS CONTROL ROOM
                </span>
                <span className="text-[10px] text-overlay mono mt-0.5">
                    Live MQTT telemetry | secure WebSocket ready
                </span>
            </div>

            {/* Right live counters */}
            <div className="flex flex-wrap items-center gap-2 text-[10px] mono">
                <span className="px-2.5 py-1 rounded-full border border-green/25 bg-green/10 text-green font-bold">
                    {onlineCount}/10 ONLINE
                </span>
                <span className="px-2.5 py-1 rounded-full border border-surface0/45 bg-surface0/30 text-overlay font-bold">
                    STATE: {cfg.label.toUpperCase().replace("...", "")}
                </span>
                <span className={`px-2.5 py-1 rounded-full border font-bold ${faultCount > 0 ? "border-orange/25 bg-orange/10 text-orange animate-pulse" : "border-surface0/45 bg-surface0/30 text-overlay"}`}>
                    {faultCount} FAULT{faultCount === 1 ? "" : "S"}
                </span>
            </div>
        </div>
    );
}

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
        <div className={`flex items-center justify-between px-4 py-2 border-b border-surface0 ${cfg.bg}`}>
            {/* Left — connection status */}
            <div className={`flex items-center gap-2 text-sm font-medium ${cfg.color}`}>
                <Icon size={15} className={spinning ? "animate-spin" : ""} />
                <span className="mono">{cfg.label}</span>
            </div>

            {/* Centre — system title */}
            <div className="hidden sm:block text-center">
                <span className="mono text-blue font-bold tracking-wider text-sm">
                    ⚡ WINTS CONTROL ROOM
                </span>
            </div>

            {/* Right — live counters */}
            <div className="flex items-center gap-4 text-xs mono">
                <span className="text-green">
                    <span className="font-bold">{onlineCount}</span>
                    <span className="text-overlay">/10 online</span>
                </span>
                {faultCount > 0 && (
                    <span className="text-orange font-bold animate-pulse">
                        {faultCount} fault{faultCount > 1 ? "s" : ""}
                    </span>
                )}
                <span className="text-overlay">Targets Online: {onlineCount}/10</span>
            </div>
        </div>
    );
}

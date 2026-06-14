"use client";
import { store } from "@/lib/mqttStore";
import { useStore } from "@/lib/useStore";
import { Battery, Sun, Users, Wifi } from "lucide-react";
import clsx from "clsx";

function CircularProgress({
    value,
    max = 100,
    color,
    size = 40,
    strokeWidth = 3.5,
}: {
    value: number;
    max?: number;
    color: string;
    size?: number;
    strokeWidth?: number;
}) {
    const radius = (size - strokeWidth) / 2;
    const circumference = radius * 2 * Math.PI;
    const offset = circumference - (Math.min(value, max) / max) * circumference;

    return (
        <svg width={size} height={size} className="transform -rotate-90 shrink-0 select-none">
            <circle
                cx={size / 2}
                cy={size / 2}
                r={radius}
                className="stroke-surface0/25"
                strokeWidth={strokeWidth}
                fill="transparent"
            />
            <circle
                cx={size / 2}
                cy={size / 2}
                r={radius}
                className={clsx("transition-all duration-1000 ease-out", color)}
                strokeWidth={strokeWidth}
                strokeDasharray={circumference}
                strokeDashoffset={offset}
                strokeLinecap="round"
                fill="transparent"
            />
        </svg>
    );
}

function Metric({
    icon: Icon,
    label,
    value,
    unit,
    color,
    pct,
    max,
    strokeColor,
}: {
    icon: React.ComponentType<{ size?: number | string; className?: string }>;
    label: string;
    value: string;
    unit: string;
    color: string;
    pct?: number;
    max?: number;
    strokeColor?: string;
}) {
    return (
        <div className="bg-crust/40 border border-surface0/45 rounded-xl p-3 flex items-center justify-between gap-3 shadow-md hover:border-surface1/60 hover:bg-crust/60 transition-all duration-300">
            <div className="flex flex-col gap-0.5 overflow-hidden">
                <div className="flex items-center gap-1.5 select-none">
                    <Icon size={12} className={color} />
                    <span className="text-[8px] text-overlay font-bold mono uppercase tracking-wider">{label}</span>
                </div>
                <div className="flex items-baseline gap-0.5 mt-1.5">
                    <span className={`text-lg font-black mono leading-none ${color}`}>{value}</span>
                    {unit && <span className="text-[9px] text-overlay font-bold ml-0.5">{unit}</span>}
                </div>
            </div>
            {pct !== undefined && (
                <CircularProgress value={pct} max={max} color={strokeColor || "stroke-blue"} />
            )}
        </div>
    );
}

export default function MetricsPanel() {
    useStore(); // subscribe to updates

    const online = store.getOnlineCount();
    const faults = store.getFaultCount();
    const avgSoc = store.getAvgSoc();
    const solar = store.getTotalSolar();

    const targets = Object.values(store.targets);
    const rssis = targets.filter(t => t.online).map(t => t.rssiDbm);
    const avgRssi = rssis.length ? rssis.reduce((a, b) => a + b, 0) / rssis.length : -100;

    const rssiPercent = Math.max(0, Math.min(100, ((avgRssi + 100) / 70) * 100));

    const lowest = targets.reduce<{ id: string; soc: number } | null>((acc, t) => {
        if (!t.online) return acc;
        if (!acc || t.batterySoc < acc.soc) return { id: t.targetId, soc: t.batterySoc };
        return acc;
    }, null);

    return (
        <div className="flex flex-col gap-3.5 p-4 border-b border-surface0/50 lg:border-b-0 lg:border-l lg:border-surface0/50 lg:w-56 lg:min-w-56 glass-panel select-none">
            <h2 className="text-[10px] font-black text-overlay uppercase tracking-widest mono border-b border-surface0/40 pb-2">
                Telemetry Analytics
            </h2>

            <Metric 
                icon={Users} 
                label="Nodes Online" 
                value={`${online}/10`} 
                unit="" 
                color="text-green" 
                pct={online} 
                max={10} 
                strokeColor="stroke-green" 
            />
            <Metric 
                icon={Wifi} 
                label="Avg RSSI" 
                value={avgRssi.toFixed(0)} 
                unit="dBm" 
                color="text-blue" 
                pct={rssiPercent} 
                max={100} 
                strokeColor={avgRssi > -65 ? "stroke-green" : avgRssi > -80 ? "stroke-yellow" : "stroke-red"} 
            />
            <Metric 
                icon={Battery} 
                label="Avg Battery" 
                value={avgSoc.toFixed(1)} 
                unit="%" 
                color={avgSoc > 50 ? "text-green" : avgSoc > 20 ? "text-yellow" : "text-red"} 
                pct={avgSoc} 
                max={100} 
                strokeColor={avgSoc > 50 ? "stroke-green" : avgSoc > 20 ? "stroke-yellow" : "stroke-red"} 
            />
            <Metric 
                icon={Sun} 
                label="Solar Harvest" 
                value={solar.toFixed(0)} 
                unit="W" 
                color="text-yellow" 
                pct={solar} 
                max={1500} 
                strokeColor="stroke-yellow" 
            />

            {faults > 0 && (
                <div className="bg-orange/5 border border-orange/35 rounded-xl p-3 text-center animate-pulse shadow-[0_0_12px_rgba(250,179,135,0.12)]">
                    <div className="text-orange font-black mono text-xl">{faults}</div>
                    <div className="text-orange/80 text-[8px] font-extrabold mono uppercase tracking-wider">Active Fault{faults > 1 ? "s" : ""}</div>
                </div>
            )}

            {lowest && (
                <div className="bg-crust/30 border border-surface0/45 rounded-xl p-3 flex flex-col gap-1.5 shadow-sm">
                    <div className="text-[8px] text-overlay font-bold mono tracking-wider uppercase">Lowest Charge Node</div>
                    <div className="flex justify-between items-baseline">
                        <span className="font-extrabold mono text-xs text-text">{lowest.id}</span>
                        <span className={`font-black mono text-sm ${lowest.soc < 20 ? "text-red animate-pulse" : "text-yellow"}`}>
                            {lowest.soc.toFixed(1)}%
                        </span>
                    </div>
                </div>
            )}
        </div>
    );
}

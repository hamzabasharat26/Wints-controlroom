"use client";
import { TargetState, store } from "@/lib/mqttStore";
import clsx from "clsx";
import { AlertTriangle, Battery, ChevronDown, ChevronUp, Square, Sun, Zap } from "lucide-react";
import { useCallback, useState } from "react";

interface Props {
    target: TargetState;
}

type Cmd = "raise" | "lower" | "stop";

function StatusBadge({ target }: { target: TargetState }) {
    if (!target.online || target.isStale) {
        const isStale = target.isStale && target.online;
        return (
            <span
                className={clsx(
                    "px-2.5 py-0.5 rounded-full text-[9px] font-black mono tracking-wider",
                    isStale
                        ? "bg-overlay/10 text-overlay border border-overlay/25"
                        : "bg-red/10 text-red border border-red/25"
                )}
            >
                {isStale ? "STALE" : "OFFLINE"}
            </span>
        );
    }
    if (target.fault) {
        return (
            <span className="px-2.5 py-0.5 rounded-full text-[9px] font-black mono tracking-wider bg-orange/10 text-orange border border-orange/20 animate-pulse">
                FAULT
            </span>
        );
    }
    return (
        <span className="px-2.5 py-0.5 rounded-full text-[9px] font-black mono tracking-wider bg-green/10 text-green border border-green/20">
            ONLINE
        </span>
    );
}

function MastIndicator({ pct }: { pct: number; position: string }) {
    const headColor =
        pct > 90 ? "var(--green)" : pct > 10 ? "var(--blue)" : "var(--overlay)";
    const bottomPct = Math.max(0, Math.min(100, pct));

    return (
        <div className="flex flex-col items-center gap-0.5 select-none shrink-0">
            <span className="text-[8px] text-overlay font-bold mono">UP</span>
            <div className="mast-track relative flex flex-col justify-between items-center py-1">
                <div className="w-2.5 h-[1px] bg-surface0/60" />
                <div className="w-1.5 h-[1px] bg-surface0/40" />
                <div className="w-2.5 h-[1px] bg-surface0/60" />
                <div className="w-1.5 h-[1px] bg-surface0/40" />
                <div className="w-2.5 h-[1px] bg-surface0/60" />
                <div
                    className="mast-head transition-all duration-350"
                    style={{
                        bottom: `calc(${bottomPct}% * 0.85 + 2px)`,
                        backgroundColor: headColor,
                        color: headColor,
                    }}
                />
            </div>
            <span className="text-[8px] text-overlay font-bold mono">DN</span>
        </div>
    );
}

function BatteryBar({ soc, charging }: { soc: number; charging: boolean }) {
    const textColor = soc > 50 ? "text-green" : soc > 20 ? "text-yellow" : "text-red font-bold animate-pulse";
    const barBgColor = soc > 50 ? "bg-green" : soc > 20 ? "bg-yellow" : "bg-red";

    return (
        <div className="w-full bg-surface0/20 border border-surface0/30 rounded-xl p-2 flex flex-col gap-1.5">
            <div className="flex justify-between items-center text-[9px] text-overlay mono font-bold">
                <span className="flex items-center gap-1 select-none">
                    <Battery size={10} className={soc <= 20 ? "text-red animate-pulse" : "text-overlay"} />
                    BATTERY
                </span>
                <span className={textColor}>
                    {charging && <span className="text-green animate-pulse mr-1">+</span>}
                    {soc.toFixed(1)}%
                </span>
            </div>
            <div className="h-2 bg-crust rounded-full overflow-hidden relative border border-surface0/20 p-[1px]">
                <div
                    className={clsx(
                        "h-full rounded-full transition-all duration-1000 relative",
                        barBgColor,
                        soc <= 20 && !charging && "battery-critical"
                    )}
                    style={{ width: `${Math.max(3, soc)}%` }}
                >
                    {charging && (
                        <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/30 to-transparent animate-pulse" />
                    )}
                </div>
            </div>
        </div>
    );
}

function RssiDots({ rssi }: { rssi: number }) {
    const bars = rssi > -55 ? 5 : rssi > -65 ? 4 : rssi > -72 ? 3 : rssi > -80 ? 2 : rssi > -90 ? 1 : 0;
    const colorClass = bars >= 4 ? "bg-green shadow-[0_0_8px_rgba(166,227,161,0.5)]" : bars >= 2 ? "bg-yellow shadow-[0_0_8px_rgba(249,226,175,0.5)]" : "bg-red shadow-[0_0_8px_rgba(243,139,168,0.5)]";
    return (
        <div className="flex items-end gap-[2px] h-7" title={`RSSI: ${rssi} dBm`}>
            {[1, 2, 3, 4, 5].map((b) => (
                <div
                    key={b}
                    className={clsx(
                        "w-1 rounded-sm transition-all duration-300",
                        b <= bars ? colorClass : "bg-surface0"
                    )}
                    style={{ height: `${3 + b * 2.5}px` }}
                />
            ))}
        </div>
    );
}

function PositionDisplay({ pct, position }: { pct: number; position: string }) {
    const color =
        position === "UP"
            ? "text-green font-black drop-shadow-[0_0_6px_rgba(166,227,161,0.25)]"
            : position === "DOWN"
              ? "text-overlay"
              : "text-blue animate-pulse";
    return (
        <div className="flex flex-col select-none">
            <span className="text-[8px] text-overlay font-bold mono uppercase tracking-wider">Mast Pos</span>
            <span className={clsx("text-base font-black leading-tight", color)}>{position}</span>
            <span className="text-[9px] text-text/80 mono bg-surface0/45 px-1.5 py-0.5 rounded border border-surface0/35 w-fit mt-1">{pct.toFixed(1)}%</span>
        </div>
    );
}

export default function TargetCard({ target }: Props) {
    const [pending, setPending] = useState<Cmd | null>(null);

    const sendCmd = useCallback((cmd: Cmd) => {
        if (pending) return;
        setPending(cmd);
        store.publishCommand(target.targetId, cmd);
        // Clear after 2 s; the MQTT status update is the real acknowledgement.
        setTimeout(() => setPending(null), 2000);
    }, [pending, target.targetId]);

    const isOnline = target.online && !target.isStale && !target.fault;
    const canRaise = isOnline && target.position !== "UP";
    const canLower = isOnline && target.position !== "DOWN";
    const canStop = target.online && !target.isStale;

    return (
        <div
            className={clsx(
                "glass-card rounded-2xl p-4 flex flex-col gap-3.5 transition-all duration-300 animate-fade-in",
                !target.online
                    ? "border-red/25 hover:border-red/40 glow-offline grayscale opacity-80"
                    : target.isStale
                      ? "border-overlay/30 opacity-80"
                      : target.fault
                        ? "border-orange/40 hover:border-orange/60 glow-fault"
                        : "border-surface0 hover:border-green/50 hover:shadow-[0_0_15px_rgba(166,227,161,0.15)] glow-online"
            )}
        >
            <div className="flex items-center justify-between border-b border-surface0/40 pb-2">
                <div className="flex items-center gap-2">
                    <span
                        className={clsx(
                            "w-2 h-2 rounded-full",
                            !target.online || target.isStale ? "bg-red animate-pulse" :
                            target.fault ? "bg-orange animate-ping" : "bg-green animate-pulse"
                        )}
                    />
                    <span className="mono font-black text-sm text-blue tracking-wider">{target.targetId}</span>
                </div>
                <StatusBadge target={target} />
            </div>

            <div className="flex items-center gap-4 py-1">
                <MastIndicator pct={target.positionPct} position={target.position} />
                <PositionDisplay pct={target.positionPct} position={target.position} />
            </div>

            <BatteryBar soc={target.batterySoc} charging={target.solarW > 0} />

            <div className="grid grid-cols-3 gap-1.5 bg-crust/50 border border-surface0/30 rounded-xl p-2 items-center text-center">
                <div className="flex flex-col items-center gap-0.5 text-[10px] text-overlay select-none">
                    <span className="mono uppercase tracking-wider text-[7px] font-bold text-overlay/80">Current</span>
                    <div className="flex items-center gap-1 text-text mt-0.5">
                        <Zap size={10} className="text-orange" />
                        <span className="mono font-bold text-[11px]">{target.motorCurrentA.toFixed(1)}A</span>
                    </div>
                </div>

                <div className="flex flex-col items-center gap-0.5 text-[10px] text-overlay select-none">
                    <span className="mono uppercase tracking-wider text-[7px] font-bold text-overlay/80">Solar</span>
                    <div className="flex items-center gap-1 text-text mt-0.5">
                        <Sun size={10} className={clsx("text-yellow", target.solarW > 0 && "animate-spin-slow")} />
                        <span className="mono font-bold text-[11px]">{target.solarW.toFixed(0)}W</span>
                    </div>
                </div>

                <div className="flex flex-col items-center gap-0.5 text-[10px] text-overlay select-none">
                    <span className="mono uppercase tracking-wider text-[7px] font-bold text-overlay/80">RSSI</span>
                    <div className="flex items-center gap-1 text-text justify-center w-full mt-0.5">
                        <RssiDots rssi={target.rssiDbm} />
                    </div>
                </div>
            </div>

            {target.fault && target.faultCode && (
                <div className="flex items-center gap-1.5 bg-red/10 border border-red/20 rounded-lg px-2.5 py-1">
                    <AlertTriangle size={11} className="text-red animate-pulse" />
                    <span className="text-red text-[9px] mono font-bold uppercase tracking-wider">{target.faultCode}</span>
                </div>
            )}

            <div className="grid grid-cols-3 gap-1.5 mt-auto pt-2 border-t border-surface0/30">
                <button
                    onClick={() => sendCmd("raise")}
                    disabled={!canRaise || pending !== null}
                    className={clsx(
                        "flex flex-col items-center justify-center py-2 rounded-xl text-[10px] font-extrabold mono transition-all border",
                        canRaise && !pending
                            ? "bg-green/5 text-green border-green/30 hover:bg-green/15 hover:border-green/55 hover:shadow-[0_0_8px_rgba(166,227,161,0.25)] cursor-pointer active:scale-90"
                            : "bg-surface0/20 text-overlay/40 border-surface0/35 cursor-not-allowed opacity-40"
                    )}
                >
                    {pending === "raise" ? (
                        <span className="text-yellow animate-pulse flex items-center gap-1 font-bold">...</span>
                    ) : (
                        <><ChevronUp size={14} /><span>RAISE</span></>
                    )}
                </button>

                <button
                    onClick={() => sendCmd("stop")}
                    disabled={!canStop || pending !== null}
                    className={clsx(
                        "flex flex-col items-center justify-center py-2 rounded-xl text-[10px] font-extrabold mono transition-all border",
                        canStop && !pending
                            ? "bg-yellow/5 text-yellow border-yellow/30 hover:bg-yellow/15 hover:border-yellow/55 hover:shadow-[0_0_8px_rgba(249,226,175,0.25)] cursor-pointer active:scale-90"
                            : "bg-surface0/20 text-overlay/40 border-surface0/35 cursor-not-allowed opacity-40"
                    )}
                >
                    {pending === "stop" ? (
                        <span className="text-yellow animate-pulse flex items-center gap-1 font-bold">...</span>
                    ) : (
                        <><Square size={10} /><span>STOP</span></>
                    )}
                </button>

                <button
                    onClick={() => sendCmd("lower")}
                    disabled={!canLower || pending !== null}
                    className={clsx(
                        "flex flex-col items-center justify-center py-2 rounded-xl text-[10px] font-extrabold mono transition-all border",
                        canLower && !pending
                            ? "bg-blue/5 text-blue border-blue/30 hover:bg-blue/15 hover:border-blue/55 hover:shadow-[0_0_8px_rgba(137,180,250,0.25)] cursor-pointer active:scale-90"
                            : "bg-surface0/20 text-overlay/40 border-surface0/35 cursor-not-allowed opacity-40"
                    )}
                >
                    {pending === "lower" ? (
                        <span className="text-yellow animate-pulse flex items-center gap-1 font-bold">...</span>
                    ) : (
                        <><ChevronDown size={14} /><span>LOWER</span></>
                    )}
                </button>
            </div>
        </div>
    );
}

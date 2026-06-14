"use client";
import { store } from "@/lib/mqttStore";
import { useStore } from "@/lib/useStore";
import clsx from "clsx";

const TYPE_STYLES = {
    info: "bg-blue/10 text-blue border-blue/20",
    cmd: "bg-mauve/10 text-mauve border-mauve/20",
    warn: "bg-yellow/10 text-yellow border-yellow/20",
    error: "bg-red/10 text-red border-red/20",
    status: "bg-green/10 text-green border-green/20",
} as const;

const TYPE_PREFIX = {
    info: "INFO",
    cmd: "CMD",
    warn: "WARN",
    error: "ERR",
    status: "OK",
} as const;

export default function EventLog() {
    useStore();
    const events = store.events.slice(0, 60);

    return (
        <div className="flex flex-col h-full glass-panel">
            <div className="px-3.5 py-2.5 border-b border-surface0/40 flex items-center justify-between select-none">
                <span className="text-[10px] font-black text-overlay uppercase tracking-widest mono">
                    Event Registry
                </span>
                <span className="text-[8px] text-overlay font-bold mono bg-surface0/45 px-2 py-0.5 rounded-md border border-surface0/30">
                    {store.events.length} entries
                </span>
            </div>

            <div className="flex-1 overflow-y-auto p-2 space-y-1 font-mono scrollbar-thin">
                {events.length === 0 ? (
                    <div className="text-overlay text-center py-6 text-xs select-none">
                        Awaiting data packets...
                    </div>
                ) : (
                    events.map((e) => {
                        const d = new Date(e.ts);
                        const ts = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}.${String(d.getMilliseconds()).padStart(3, "0")}`;
                        return (
                            <div
                                key={e.id}
                                className="flex gap-2.5 px-2 py-1.5 rounded-lg hover:bg-surface0/30 transition-colors border border-transparent hover:border-surface0/30 items-center animate-fade-in"
                            >
                                <span className="text-[8px] text-overlay font-bold shrink-0 select-none">[{ts}]</span>
                                <span className={clsx("shrink-0 px-2 py-0.5 rounded-md text-[8px] font-black border tracking-wide select-none", TYPE_STYLES[e.type])}>
                                    {TYPE_PREFIX[e.type]}
                                </span>
                                <span className="text-text break-all flex-1 text-[9.5px] leading-relaxed">{e.message}</span>
                            </div>
                        );
                    })
                )}
            </div>
        </div>
    );
}

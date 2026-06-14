/**
 * mqttStore.ts
 * Central MQTT connection + state store for the WINTS web dashboard.
 * Uses browser-native mqtt.js over secure WebSocket (wss://).
 *
 * Target state is updated on every incoming wints/T-XX/status and
 * wints/T-XX/telemetry message, then notifies all registered listeners.
 */

import mqtt, { MqttClient } from "mqtt";

// ── Types ───────────────────────────────────────────────────────────────────

export type PositionLabel = "UP" | "DOWN" | "MOVING" | "UNKNOWN";
export type FaultCode =
    | "OVERCURRENT"
    | "BMS_CUTOFF"
    | "LIMIT_STUCK"
    | "MOTOR_STALL"
    | null;

export interface TargetState {
    targetId: string;
    online: boolean;
    position: PositionLabel;
    positionPct: number;
    batterySoc: number;
    batteryVoltage: number;
    fault: boolean;
    faultCode: FaultCode;
    rssiDbm: number;
    packetLossPct: number;
    motorCurrentA: number;
    solarW: number;
    lastUpdateTs: number;
    isStale: boolean;
}

export interface EventEntry {
    id: number;
    ts: number;
    type: "info" | "cmd" | "warn" | "error" | "status";
    message: string;
}

export type ConnectionState = "disconnected" | "connecting" | "connected" | "error";

// ── Initial state ───────────────────────────────────────────────────────────

const TARGET_IDS = Array.from({ length: 10 }, (_, i) => `T-${String(i + 1).padStart(2, "0")}`);

function makeDefaultTarget(id: string): TargetState {
    return {
        targetId: id,
        online: false,
        position: "UNKNOWN",
        positionPct: 0,
        batterySoc: 0,
        batteryVoltage: 0,
        fault: false,
        faultCode: null,
        rssiDbm: -100,
        packetLossPct: 0,
        motorCurrentA: 0,
        solarW: 0,
        lastUpdateTs: 0,
        isStale: true,
    };
}

// ── Store singleton ─────────────────────────────────────────────────────────

type Listener = () => void;

class WINTSStore {
    targets: Record<string, TargetState> = {};
    events: EventEntry[] = [];
    connection: ConnectionState = "disconnected";
    private client: MqttClient | null = null;
    private listeners: Set<Listener> = new Set();
    private eventCounter = 0;
    private staleTimer: ReturnType<typeof setInterval> | null = null;

    constructor() {
        for (const id of TARGET_IDS) {
            this.targets[id] = makeDefaultTarget(id);
        }
    }

    // ── Subscription ──────────────────────────────────────────────────────────

    subscribe(fn: Listener) {
        this.listeners.add(fn);
        return () => this.listeners.delete(fn);
    }

    private notify() {
        this.listeners.forEach((fn) => fn());
    }

    // ── Events ────────────────────────────────────────────────────────────────

    private addEvent(type: EventEntry["type"], message: string) {
        const entry: EventEntry = {
            id: ++this.eventCounter,
            ts: Date.now(),
            type,
            message,
        };
        // Keep last 200 events
        this.events = [entry, ...this.events].slice(0, 200);
    }

    // ── MQTT connection ───────────────────────────────────────────────────────

    private normalizeHost(host: string): string {
        const raw = host.trim();
        const withoutProtocol = raw.replace(/^wss?:\/\//i, "").replace(/^https?:\/\//i, "");
        const withoutPath = withoutProtocol.split("/")[0] ?? "";
        return withoutPath.trim();
    }

    private isPlaceholder(value: string): boolean {
        const v = value.trim().toLowerCase();
        return (
            !v ||
            v.includes("your_cluster") ||
            v.includes("your-broker") ||
            v.includes("example") ||
            v.includes("placeholder")
        );
    }

    connect(host: string, port: number, username: string, password: string) {
        if (this.client) return;

        const normalizedHost = this.normalizeHost(host);
        const normalizedPort = Number.isFinite(port) ? Math.trunc(port) : NaN;

        if (
            this.isPlaceholder(normalizedHost) ||
            !Number.isFinite(normalizedPort) ||
            normalizedPort <= 0 ||
            this.isPlaceholder(username) ||
            this.isPlaceholder(password)
        ) {
            this.connection = "error";
            this.addEvent("error", "Broker config is invalid. Open Configure Broker and enter real values.");
            this.notify();
            return;
        }

        this.connection = "connecting";
        this.notify();

        const url = `wss://${normalizedHost}:${normalizedPort}/mqtt`;

        this.client = mqtt.connect(url, {
            username,
            password,
            clientId: `wints-web-${Math.random().toString(36).slice(2, 10)}`,
            clean: true,
            reconnectPeriod: 3000,
            connectTimeout: 10000,
            rejectUnauthorized: false,
        });

        this.client.on("connect", () => {
            this.connection = "connected";
            this.addEvent("info", "Connected to MQTT broker");
            // Subscribe to all WINTS topics
            this.client!.subscribe("wints/+/status", { qos: 1 });
            this.client!.subscribe("wints/+/telemetry", { qos: 0 });
            this.notify();
            // Start stale detection
            this.startStaleDetection();
        });

        this.client.on("disconnect", () => {
            this.connection = "disconnected";
            this.addEvent("warn", "Disconnected from broker");
            this.notify();
        });

        this.client.on("error", (err) => {
            this.connection = "error";
            this.addEvent("error", `Broker error: ${err.message}`);
            this.notify();
        });

        this.client.on("reconnect", () => {
            this.connection = "connecting";
            this.addEvent("info", "Reconnecting to broker...");
            this.notify();
        });

        this.client.on("message", (topic: string, payload: Buffer) => {
            this.handleMessage(topic, payload.toString());
        });
    }

    disconnect() {
        this.client?.end(true);
        this.client = null;
        this.connection = "disconnected";
        if (this.staleTimer) clearInterval(this.staleTimer);
        this.notify();
    }

    // ── Message handler ───────────────────────────────────────────────────────

    private handleMessage(topic: string, raw: string) {
        try {
            const parts = topic.split("/"); // ["wints", "T-01", "status"]
            if (parts.length !== 3 || parts[0] !== "wints") return;

            const targetId = parts[1];
            const msgType = parts[2];

            if (!TARGET_IDS.includes(targetId)) return;

            const data = JSON.parse(raw);

            if (msgType === "status") {
                this.targets = {
                    ...this.targets,
                    [targetId]: {
                        ...this.targets[targetId],
                        online: data.online ?? false,
                        position: (data.position as PositionLabel) ?? "UNKNOWN",
                        positionPct: data.position_pct ?? 0,
                        batterySoc: data.battery_soc ?? 0,
                        batteryVoltage: data.battery_voltage ?? 0,
                        fault: data.fault ?? false,
                        faultCode: (data.fault_code as FaultCode) ?? null,
                        lastUpdateTs: Date.now(),
                        isStale: false,
                    },
                };

                if (data.fault && data.fault_code) {
                    this.addEvent("warn", `${targetId}: FAULT — ${data.fault_code}`);
                }
                if (!data.online) {
                    this.addEvent("error", `${targetId}: went OFFLINE`);
                }
            }

            if (msgType === "telemetry") {
                this.targets = {
                    ...this.targets,
                    [targetId]: {
                        ...this.targets[targetId],
                        rssiDbm: data.rssi_dbm ?? -100,
                        packetLossPct: data.packet_loss_pct ?? 0,
                        motorCurrentA: data.motor_current_a ?? 0,
                        solarW: data.solar_w ?? 0,
                        lastUpdateTs: Date.now(),
                        isStale: false,
                    },
                };
            }

            this.notify();
        } catch {
            // Malformed JSON — silently discard
        }
    }

    // ── Command publish ───────────────────────────────────────────────────────

    publishCommand(targetId: string, cmd: "raise" | "lower" | "stop") {
        if (!this.client || this.connection !== "connected") return;

        const traceId = crypto.randomUUID();
        const topic =
            targetId === "broadcast"
                ? "wints/broadcast/cmd"
                : `wints/${targetId}/cmd`;

        const payload = JSON.stringify({
            trace_id: traceId,
            cmd,
            ts: Date.now(),
        });

        this.client.publish(topic, payload, { qos: 1 });

        const label = targetId === "broadcast" ? "ALL" : targetId;
        this.addEvent("cmd", `[CMD] ${label} → ${cmd.toUpperCase()} [${traceId.slice(0, 8)}]`);
        this.notify();

        return traceId;
    }

    // ── Stale detection ───────────────────────────────────────────────────────

    private startStaleDetection() {
        if (this.staleTimer) clearInterval(this.staleTimer);
        this.staleTimer = setInterval(() => {
            const now = Date.now();
            let changed = false;
            const updated = { ...this.targets };
            for (const id of TARGET_IDS) {
                const t = updated[id];
                if (t.online && t.lastUpdateTs > 0 && now - t.lastUpdateTs > 10_000) {
                    updated[id] = { ...t, isStale: true };
                    changed = true;
                }
            }
            if (changed) {
                this.targets = updated;
                this.notify();
            }
        }, 2000);
    }

    // ── Derived metrics ───────────────────────────────────────────────────────

    getOnlineCount(): number {
        return Object.values(this.targets).filter((t) => t.online && !t.isStale).length;
    }

    getFaultCount(): number {
        return Object.values(this.targets).filter((t) => t.fault).length;
    }

    getAvgSoc(): number {
        const online = Object.values(this.targets).filter((t) => t.online);
        if (!online.length) return 0;
        return online.reduce((s, t) => s + t.batterySoc, 0) / online.length;
    }

    getTotalSolar(): number {
        return Object.values(this.targets).reduce((s, t) => s + (t.online ? t.solarW : 0), 0);
    }
}

// Export singleton
export const store = new WINTSStore();

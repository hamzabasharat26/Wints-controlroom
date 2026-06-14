"use client";
import { store } from "@/lib/mqttStore";
import { ExternalLink, Wifi } from "lucide-react";
import { useEffect, useState } from "react";

interface Props {
    defaultOpen?: boolean;
}

export default function BrokerConnect({ defaultOpen = false }: Props) {
    const [host, setHost] = useState("");
    const [port, setPort] = useState("8884");
    const [username, setUsername] = useState("");
    const [password, setPassword] = useState("");
    const [show, setShow] = useState(false);

    useEffect(() => {
        if (defaultOpen) {
            setShow(true);
        }
    }, [defaultOpen]);

    // Pre-fill from env vars
    useEffect(() => {
        setHost(process.env.NEXT_PUBLIC_MQTT_HOST ?? "");
        setPort(process.env.NEXT_PUBLIC_MQTT_PORT ?? "8884");
        setUsername(process.env.NEXT_PUBLIC_MQTT_USERNAME ?? "");
        setPassword(process.env.NEXT_PUBLIC_MQTT_PASSWORD ?? "");
    }, []);

    const handleConnect = () => {
        store.connect(host, parseInt(port), username, password);
        setShow(false);
    };

    // Auto-connect if env vars are set
    useEffect(() => {
        if (host && username && password && store.connection === "disconnected") {
            store.connect(host, parseInt(port), username, password);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [host]);

    if (!show) {
        return (
            <button
                onClick={() => setShow(true)}
                className="flex items-center gap-2 px-3 py-1.5 bg-surface0 hover:bg-surface1 text-text text-xs mono rounded-lg border border-surface1 transition-all"
            >
                <Wifi size={13} />
                Configure Broker
            </button>
        );
    }

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
            <div className="bg-mantle border border-surface0 rounded-2xl p-6 w-full max-w-md shadow-2xl animate-slide-up">
                <h2 className="text-base font-bold mono text-blue mb-1">Connect to MQTT Broker</h2>
                <p className="text-xs text-overlay mb-4">
                    Use{" "}
                    <a
                        href="https://console.hivemq.cloud"
                        target="_blank"
                        rel="noreferrer"
                        className="text-blue hover:underline inline-flex items-center gap-1"
                    >
                        HiveMQ Cloud Free <ExternalLink size={10} />
                    </a>{" "}
                    for a free WebSocket MQTT broker.
                </p>

                <div className="flex flex-col gap-3">
                    <div>
                        <label className="text-[10px] text-overlay mono uppercase tracking-wider">Host</label>
                        <input
                            value={host}
                            onChange={(e) => setHost(e.target.value)}
                            placeholder="abc123.s1.eu.hivemq.cloud"
                            className="w-full mt-1 px-3 py-2 bg-surface0 border border-surface1 rounded-lg text-sm mono text-text placeholder:text-overlay focus:outline-none focus:border-blue"
                        />
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                        <div>
                            <label className="text-[10px] text-overlay mono uppercase tracking-wider">Port</label>
                            <input
                                value={port}
                                onChange={(e) => setPort(e.target.value)}
                                className="w-full mt-1 px-3 py-2 bg-surface0 border border-surface1 rounded-lg text-sm mono text-text focus:outline-none focus:border-blue"
                            />
                        </div>
                        <div>
                            <label className="text-[10px] text-overlay mono uppercase tracking-wider">Username</label>
                            <input
                                value={username}
                                onChange={(e) => setUsername(e.target.value)}
                                className="w-full mt-1 px-3 py-2 bg-surface0 border border-surface1 rounded-lg text-sm mono text-text focus:outline-none focus:border-blue"
                            />
                        </div>
                    </div>
                    <div>
                        <label className="text-[10px] text-overlay mono uppercase tracking-wider">Password</label>
                        <input
                            type="password"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            className="w-full mt-1 px-3 py-2 bg-surface0 border border-surface1 rounded-lg text-sm mono text-text focus:outline-none focus:border-blue"
                        />
                    </div>
                </div>

                <div className="flex gap-3 mt-5">
                    <button
                        onClick={handleConnect}
                        className="flex-1 py-2 bg-blue text-base font-bold mono rounded-lg text-sm hover:bg-blue/90 active:scale-95 transition-all"
                    >
                        Connect
                    </button>
                    <button
                        onClick={() => setShow(false)}
                        className="px-4 py-2 bg-surface0 text-overlay mono rounded-lg text-sm hover:bg-surface1 transition-all"
                    >
                        Cancel
                    </button>
                </div>
            </div>
        </div>
    );
}

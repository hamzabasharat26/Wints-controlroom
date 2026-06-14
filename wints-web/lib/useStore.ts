"use client";
/**
 * useStore — React hook that subscribes to the WINTS store singleton
 * and triggers re-renders whenever state changes.
 */
import { useSyncExternalStore } from "react";
import { ConnectionState, EventEntry, store, TargetState } from "./mqttStore";

function getSnapshot() {
    return store;
}

function subscribe(cb: () => void) {
    return store.subscribe(cb);
}

export function useStore() {
    useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
    return store;
}

export type { ConnectionState, EventEntry, TargetState };


import { useEffect, useState, useRef } from 'react';
import * as Y from 'yjs';
import { WebsocketProvider } from 'y-websocket';
import { IndexeddbPersistence } from 'y-indexeddb';

/**
 * Returns a Yjs document synced to:
 *   - IndexedDB (on-device, offline-first)
 *   - WebSocket server (live multi-user CRDT sync)
 *
 * @param {string|null} zoneId  Shared zone ID — pass null to disable
 * @param {string|null} wsUrl   WebSocket base URL (default: current host)
 */
export function useSharedZone(zoneId, wsUrl = null) {
  const [doc]       = useState(() => new Y.Doc());
  const [connected, setConnected] = useState(false);
  const wsRef  = useRef(null);
  const idbRef = useRef(null);

  useEffect(() => {
    if (!zoneId) return;

    const wsBase = wsUrl
      || import.meta.env.VITE_WS_URL
      || ((window.location.protocol === 'https:' ? 'wss:' : 'ws:')
          + '//' + window.location.host);

    // y-websocket connects to `${serverUrl}/${roomname}` → ws://.../ws/yjs/{zoneId}
    const yjsUrl = `${wsBase}/ws/yjs`;

    // On-device persistence — survives page reload and offline periods
    idbRef.current = new IndexeddbPersistence(`oria-zone-${zoneId}`, doc);

    // Server sync via y-websocket protocol
    wsRef.current = new WebsocketProvider(yjsUrl, zoneId, doc);
    wsRef.current.on('status', ({ status }) => {
      setConnected(status === 'connected');
    });

    return () => {
      wsRef.current?.destroy();
      idbRef.current?.destroy();
    };
  }, [zoneId]);   // eslint-disable-line react-hooks/exhaustive-deps

  return { doc, connected };
}

import { useEffect, useRef, useState } from 'react';

export const API_BASE = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_BASE) ?? '/api';

export const KIND_COLORS = {
  carton: '#c9d7ab',
  box: '#e3a077',
  jar: '#e5dca4',
  bottle: '#a27f60',
  fruit: '#b6bf76',
  placeholder: '#8d95bd',
};

export function nameFor(id, roster) {
  if (id === null || id === undefined) return 'Unknown';
  if (Array.isArray(roster)) {
    const person = roster.find((p) => (p.person_id ?? p.id) === id);
    if (person && person.name) return person.name;
  } else if (roster && typeof roster === 'object') {
    if (roster[id]) {
      return typeof roster[id] === 'string' ? roster[id] : (roster[id].name || id);
    }
  }
  return id;
}

export function kindFor(label) {
  const l = (label || '').toLowerCase();
  if (l.includes('milk') || l.includes('carton') || l.includes('juice')) return 'carton';
  if (l.includes('box') || l.includes('container')) return 'box';
  if (l.includes('bottle') || l.includes('can')) return 'bottle';
  if (l.includes('jar') || l.includes('yogurt')) return 'jar';
  if (l.includes('fruit') || l.includes('apple')) return 'fruit';
  return 'placeholder';
}

export function capitalize(str) {
  if (!str) return '';
  return str.charAt(0).toUpperCase() + str.slice(1);
}

export function formatLocalTime(isoString) {
  if (!isoString) return '--:--';
  const d = new Date(isoString);
  if (isNaN(d.getTime())) return '--:--';
  return d.toTimeString().slice(0, 5);
}

export function mapInventory(rows, roster) {
  const sorted = [...(rows || [])].sort((a, b) => new Date(a.since_ts) - new Date(b.since_ts));
  const usedSlots = new Set();
  const preferredSlots = {
    carton: [0, 5],
    box: [1],
    jar: [2],
    bottle: [3],
    fruit: [4],
  };

  return sorted.map((row) => {
    const kind = kindFor(row.item_label);
    let slot = undefined;
    if (kind !== 'placeholder') {
      const preferred = preferredSlots[kind] || [];
      const freePref = preferred.find((s) => !usedSlots.has(s));
      if (freePref !== undefined) {
        slot = freePref;
      } else {
        const fallback = [0, 1, 2, 3, 4, 5].find((s) => !usedSlots.has(s));
        if (fallback !== undefined) {
          slot = fallback;
        }
      }
      if (slot !== undefined) {
        usedSlots.add(slot);
      }
    }

    return {
      id: row.item_id,
      name: capitalize(row.item_label),
      owner: nameFor(row.owner_id, roster),
      kind,
      color: KIND_COLORS[kind] || KIND_COLORS.placeholder,
      time: formatLocalTime(row.since_ts),
      placeholder: kind === 'placeholder',
      slot,
    };
  });
}

const STATUS_TO_RESULT = {
  ok: 'Verified',
  wrong_owner: 'Mismatch',
  uncertain: 'Uncertain',
};

export function mapEvent(ev, roster) {
  const result = STATUS_TO_RESULT[ev.status] || ev.status;
  const confNum = typeof ev.confidence === 'number' ? ev.confidence : Number(ev.confidence) || 0;
  return {
    id: ev.event_id,
    time: formatLocalTime(ev.ts),
    action: ev.type,
    item: capitalize(ev.item_label),
    person: nameFor(ev.person_id, roster),
    owner: nameFor(ev.owner_id, roster),
    result,
    confidence: `${Math.round(confNum * 100)}%`,
  };
}

export function useFridgeData() {
  const [data, setData] = useState({
    mode: 'demo',
    stale: false,
    inventory: [],
    events: [],
    people: [],
  });

  const refetchRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    let pollTimer = null;
    let burstTimer = null;
    let eventSource = null;
    let isFirstLoad = true;
    let currentMode = 'demo';

    function stopPolling() {
      if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    }

    function startPolling() {
      if (!pollTimer && !cancelled) {
        pollTimer = setInterval(() => {
          fetchAll();
        }, 5000);
      }
    }

    async function fetchAll() {
      try {
        const [invRes, evRes, peopRes] = await Promise.all([
          fetch(`${API_BASE}/inventory`),
          fetch(`${API_BASE}/events?limit=100`),
          fetch(`${API_BASE}/people`),
        ]);

        if (!invRes.ok || !evRes.ok || !peopRes.ok) {
          throw new Error('API request failed');
        }

        const [invData, evData, peopData] = await Promise.all([
          invRes.json(),
          evRes.json(),
          peopRes.json(),
        ]);

        if (cancelled) return;

        currentMode = 'live';
        isFirstLoad = false;

        setData({
          mode: 'live',
          stale: false,
          inventory: mapInventory(invData, peopData),
          events: evData.map((ev) => mapEvent(ev, peopData)),
          people: peopData,
        });

        if (eventSource && eventSource.readyState === EventSource.OPEN) {
          stopPolling();
        }
      } catch {
        if (cancelled) return;

        if (isFirstLoad) {
          isFirstLoad = false;
          currentMode = 'demo';
          setData((prev) => ({ ...prev, mode: 'demo', stale: false }));
          startPolling();
        } else if (currentMode === 'live') {
          setData((prev) => ({ ...prev, stale: true }));
          startPolling();
        } else {
          setData((prev) => ({ ...prev, mode: 'demo', stale: false }));
          startPolling();
        }
      }
    }

    refetchRef.current = fetchAll;

    function scheduleBurstFetch() {
      if (burstTimer) return;
      burstTimer = setTimeout(() => {
        burstTimer = null;
        if (!cancelled) fetchAll();
      }, 300);
    }

    fetchAll();

    try {
      eventSource = new EventSource(`${API_BASE}/stream`);

      eventSource.addEventListener('fridge.event', () => {
        scheduleBurstFetch();
      });

      eventSource.onopen = () => {
        if (currentMode === 'live') {
          fetchAll();
        }
      };

      eventSource.onerror = () => {
        startPolling();
      };
    } catch {
      startPolling();
    }

    return () => {
      cancelled = true;
      refetchRef.current = null;
      stopPolling();
      if (burstTimer) {
        clearTimeout(burstTimer);
        burstTimer = null;
      }
      if (eventSource) {
        eventSource.close();
        eventSource = null;
      }
    };
  }, []);

  return {
    ...data,
    refetch: () => refetchRef.current?.(),
  };
}

// frontend/src/hooks/useGameLog.ts
import { useState, useCallback } from 'react';

interface GameLogEvent {
  id: string;
  type: string;
  message: string;
  timestamp: number;
  turn?: number;
  phase?: string;
}

export function useGameLog() {
  const [events, setEvents] = useState<GameLogEvent[]>([]);

  const addEvent = useCallback((event: Omit<GameLogEvent, 'id' | 'timestamp'>) => {
    const newEvent: GameLogEvent = {
      ...event,
      id: `${Date.now()}-${Math.random()}`,
      timestamp: Date.now()
    };
    setEvents(prev => [...prev, newEvent].slice(-100)); // Keep last 100 events
  }, []);

  const clearEvents = useCallback(() => {
    setEvents([]);
  }, []);

  const getElapsedTime = useCallback((eventTimestamp: number) => {
    const now = Date.now();
    const elapsed = Math.floor((now - eventTimestamp) / 1000);
    if (elapsed < 60) return `${elapsed}s ago`;
    if (elapsed < 3600) return `${Math.floor(elapsed / 60)}m ago`;
    return `${Math.floor(elapsed / 3600)}h ago`;
  }, []);

  return {
    events,
    addEvent,
    clearEvents,
    getElapsedTime
  };
}
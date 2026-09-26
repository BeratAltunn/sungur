// Playback clock for the main map's time bar. Kept outside React state so a running clock redraws only the time
// bar and the vehicle layer (subscribers), not the whole triage page, on every animation frame.

export interface ClockState {
  t: number; // minutes of day
  playing: boolean;
  speed: number; // simulated minutes per real second
}

export interface Clock {
  get: () => ClockState;
  set: (patch: Partial<ClockState>) => void;
  subscribe: (fn: () => void) => () => void;
}

export function createClock(initial: ClockState): Clock {
  let state = initial;
  const subs = new Set<() => void>();
  return {
    get: () => state,
    set: (patch) => {
      state = { ...state, ...patch };
      subs.forEach((fn) => fn());
    },
    subscribe: (fn) => {
      subs.add(fn);
      return () => subs.delete(fn);
    },
  };
}

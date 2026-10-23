// Deterministic Web Locks platform stand-in; production uses the browser lock.
let sessionLock: Promise<unknown> = Promise.resolve();
Object.defineProperty(navigator, "locks", { configurable: true, value: {
  request: (_name: string, action: () => unknown) => {
    const result = sessionLock.then(action);
    sessionLock = result.catch(() => undefined);
    return result;
  },
} });
import { vi } from 'vitest'
import axios from 'axios'

// Unit tests must never reach a developer's running backend. Tests exercising
// the API provide their own mock adapter or mock the client module explicitly.
axios.defaults.adapter = async (config) => {
  throw new Error(`Unmocked unit-test HTTP request: ${config.method?.toUpperCase()} ${config.url}`)
}

// The local data story and LLM store use fetch directly. Keep that path
// offline too; individual tests can replace fetch with an explicit mock.
globalThis.fetch = async () => {
  throw new Error('Unmocked unit-test fetch request')
}

type MockIntersectionObserver = {
  new (): {
    disconnect(): void
    observe(): void
    takeRecords(): never[]
    unobserve(): void
  }
}

const createStorageMock = () => {
  const store = new Map<string, string>()
  return {
    get length() {
      return store.size
    },
    clear() {
      store.clear()
    },
    getItem(key: string) {
      return store.has(key) ? store.get(key)! : null
    },
    key(index: number) {
      return Array.from(store.keys())[index] ?? null
    },
    removeItem(key: string) {
      store.delete(key)
    },
    setItem(key: string, value: string) {
      store.set(key, String(value))
    },
  }
}

const ensureStorage = (name: 'localStorage' | 'sessionStorage') => {
  const current = globalThis[name]
  if (
    current &&
    typeof current.getItem === 'function' &&
    typeof current.setItem === 'function' &&
    typeof current.removeItem === 'function' &&
    typeof current.clear === 'function'
  ) {
    return
  }

  Object.defineProperty(globalThis, name, {
    configurable: true,
    writable: true,
    value: createStorageMock(),
  })
}

ensureStorage('localStorage')
ensureStorage('sessionStorage')

// Mock window.matchMedia
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
})

// Mock IntersectionObserver
global.IntersectionObserver = class IntersectionObserver {
  constructor() {}
  disconnect() {}
  observe() {}
  takeRecords() {
    return []
  }
  unobserve() {}
} as MockIntersectionObserver

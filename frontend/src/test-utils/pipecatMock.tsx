/**
 * A controllable fake of @pipecat-ai/client-react for component tests.
 *
 * CallStage/CallStageSession drive their entire lifecycle off these hooks —
 * transport state, mic control, media devices, conversation messages, and
 * RTVI events — with no real WebSocket to connect to in a test environment.
 * This mock lets a test script the exact sequence a real call would produce
 * (connecting → connected → bot speaks → disconnect) via `pipecatTestStore`,
 * and every mocked hook re-renders through `useSyncExternalStore` so React
 * sees the update the same way it would from the real library's state.
 *
 * State is keyed PER CLIENT OBJECT (via PipecatClientProvider's React
 * context), not global — mirroring how the real library scopes conversation
 * state to one PipecatClient instance. This matters for testing "New call":
 * BrowserCallSession gives each session a genuinely new client object (see
 * createBrowserPipecatClient mock), so a remount naturally reads fresh,
 * empty state here too, the same way it gets a fresh client in production.
 *
 * Usage in a test file:
 *   vi.mock("@pipecat-ai/client-react", () => import("@/test-utils/pipecatMock"));
 *   import { pipecatTestStore } from "@/test-utils/pipecatMock";
 *   ...
 *   act(() => pipecatTestStore.forClient(client).setTransportState("connected"));
 *   act(() => pipecatTestStore.forClient(client).disconnect());
 *
 * When a test doesn't hold a reference to the client (most don't, since
 * CallStage/CallStageSession create it internally), use
 * `pipecatTestStore.current()` to drive whichever client is currently
 * mounted — resolved via the same context the real hooks read.
 */
import { createContext, useContext, useEffect, useSyncExternalStore } from "react";
import type { ReactNode } from "react";
import { RTVIEvent, type RTVIMessage } from "@pipecat-ai/client-js";
import type { ConversationMessage } from "@pipecat-ai/client-react";

type TransportState = "disconnected" | "connecting" | "connected" | "ready" | "error";

interface FakeState {
  transportState: TransportState;
  messages: ConversationMessage[];
  micEnabled: boolean;
  availableMics: MediaDeviceInfo[];
  selectedMic: MediaDeviceInfo | undefined;
}

type Listener = () => void;
type EventHandler = (msg?: RTVIMessage) => void;

function initialState(): FakeState {
  return {
    transportState: "disconnected",
    messages: [],
    micEnabled: true,
    availableMics: [],
    selectedMic: undefined,
  };
}

interface ClientHandle {
  subscribe(listener: Listener): () => void;
  getSnapshot(): FakeState;
  setTransportState(transportState: TransportState): void;
  setMessages(messages: ConversationMessage[]): void;
  addMessage(message: ConversationMessage): void;
  setMicEnabled(micEnabled: boolean): void;
  setAvailableMics(mics: MediaDeviceInfo[]): void;
  disconnect(): void;
  _registerHandler(event: RTVIEvent, handler: EventHandler): () => void;
  emit(event: RTVIEvent, msg?: RTVIMessage): void;
}

function createClientHandle(): ClientHandle {
  let state = initialState();
  const listeners = new Set<Listener>();
  const eventHandlers = new Map<RTVIEvent, Set<EventHandler>>();

  function notify() {
    listeners.forEach((l) => l());
  }

  return {
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    getSnapshot: () => state,
    setTransportState(transportState) {
      state = { ...state, transportState };
      notify();
    },
    setMessages(messages) {
      state = { ...state, messages };
      notify();
    },
    addMessage(message) {
      state = { ...state, messages: [...state.messages, message] };
      notify();
    },
    setMicEnabled(micEnabled) {
      state = { ...state, micEnabled };
      notify();
    },
    setAvailableMics(availableMics) {
      state = { ...state, availableMics };
      notify();
    },
    /** Simulates a full disconnect the way the real client does it: the
     * transport state actually transitions to "disconnected" AND the
     * RTVIEvent.Disconnected handlers fire — both matter, since CallStage
     * derives `isConnected`/status text from transportState and `hasEnded`
     * from the event. Prefer this over a raw emit(RTVIEvent.Disconnected)
     * so tests can't accidentally leave transportState stale. */
    disconnect() {
      state = { ...state, transportState: "disconnected" };
      notify();
      eventHandlers.get(RTVIEvent.Disconnected)?.forEach((h) => h());
    },
    _registerHandler(event, handler) {
      if (!eventHandlers.has(event)) eventHandlers.set(event, new Set());
      eventHandlers.get(event)!.add(handler);
      return () => eventHandlers.get(event)?.delete(handler);
    },
    emit(event, msg) {
      eventHandlers.get(event)?.forEach((h) => h(msg));
    },
  };
}

/** Registry mapping each fake client object to its own isolated state — the
 * per-client scoping that makes "New call" (a genuinely new client) produce
 * genuinely fresh state, the same as production. */
const registry = new Map<object, ClientHandle>();
/** The most recently created client, for tests that don't hold a client
 * reference — mirrors "whichever session is currently mounted". */
let mostRecentClient: object | undefined;

export const pipecatTestStore = {
  /** Creates a new fake client object and registers its own state handle —
   * called by the mocked createBrowserPipecatClient(), one per session. */
  createClient(): object {
    const client = {};
    registry.set(client, createClientHandle());
    mostRecentClient = client;
    return client;
  },
  forClient(client: object): ClientHandle {
    const handle = registry.get(client);
    if (!handle) throw new Error("pipecatTestStore: unknown client — was it created via createClient()?");
    return handle;
  },
  /** Drives whichever client CallStageSession most recently created —
   * convenient for tests that don't need to juggle client references
   * themselves (i.e. anything not specifically testing multi-session
   * isolation). */
  current(): ClientHandle {
    if (!mostRecentClient) throw new Error("pipecatTestStore: no client created yet — render a component first.");
    return this.forClient(mostRecentClient);
  },
  /** Clears all registered clients — call in afterEach so state never
   * leaks between tests. */
  reset() {
    registry.clear();
    mostRecentClient = undefined;
  },
};

const ClientContext = createContext<object | undefined>(undefined);

export function usePipecatClient() {
  return useContext(ClientContext);
}

function useClientHandle(): ClientHandle {
  const client = useContext(ClientContext);
  if (!client) throw new Error("Mocked pipecat hook used outside PipecatClientProvider");
  return pipecatTestStore.forClient(client);
}

export function usePipecatClientTransportState(): TransportState {
  const handle = useClientHandle();
  const state = useSyncExternalStore(handle.subscribe, handle.getSnapshot);
  return state.transportState;
}

export function usePipecatClientMicControl() {
  const handle = useClientHandle();
  const state = useSyncExternalStore(handle.subscribe, handle.getSnapshot);
  return {
    enableMic: (enabled: boolean) => handle.setMicEnabled(enabled),
    isMicEnabled: state.micEnabled,
  };
}

export function usePipecatClientMediaDevices() {
  const handle = useClientHandle();
  const state = useSyncExternalStore(handle.subscribe, handle.getSnapshot);
  return {
    availableCams: [],
    availableMics: state.availableMics,
    availableSpeakers: [],
    selectedCam: undefined,
    selectedMic: state.selectedMic,
    selectedSpeaker: undefined,
    updateCam: () => {},
    updateMic: () => {},
    updateSpeaker: () => {},
  };
}

export function usePipecatConversation() {
  const handle = useClientHandle();
  const state = useSyncExternalStore(handle.subscribe, handle.getSnapshot);
  return { messages: state.messages };
}

export function useRTVIClientEvent(event: RTVIEvent, handler: EventHandler) {
  const handle = useClientHandle();
  // Mirrors the real hook's effect-based registration: register on mount,
  // unregister on unmount/handler change — same lifecycle CallStage relies
  // on (each call wraps `handler` in its own useCallback with []).
  useEffect(() => {
    return handle._registerHandler(event, handler);
  }, [handle, event, handler]);
}

export function PipecatClientProvider({
  client,
  children,
}: {
  client: object;
  children: ReactNode;
}) {
  return <ClientContext.Provider value={client}>{children}</ClientContext.Provider>;
}

export function PipecatClientAudio() {
  return null;
}

export function VoiceVisualizer() {
  return null;
}

export type {
  BotOutputText,
  ConversationMessage,
  ConversationMessagePart,
} from "@pipecat-ai/client-react";

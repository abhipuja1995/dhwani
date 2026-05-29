import { useEffect, useRef, useState } from "react";
import { SipClient, SipConfig, CallState } from "../lib/sipClient";

export function useSip(config: SipConfig | null) {
  const clientRef = useRef<SipClient | null>(null);
  const [registered, setRegistered] = useState(false);
  const [callState, setCallState] = useState<CallState>("idle");

  useEffect(() => {
    if (!config) return;
    const client = new SipClient(config);
    clientRef.current = client;
    client.onRegistered = () => setRegistered(true);
    client.onUnregistered = () => setRegistered(false);
    client.onStateChange = setCallState;
    client.start();
    return () => client.stop();
  }, [config?.username, config?.wsUri]);

  return {
    registered,
    callState,
    call: (target: string) => clientRef.current?.call(target),
    answer: () => clientRef.current?.answer(),
    hangup: () => clientRef.current?.hangup(),
    hold: () => clientRef.current?.hold(),
    unhold: () => clientRef.current?.unhold(),
    dtmf: (t: string) => clientRef.current?.sendDtmf(t),
  };
}

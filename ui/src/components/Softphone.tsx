import { useState, useEffect } from "react";
import { Phone, PhoneOff, PhoneIncoming, Pause, Play, Mic, MicOff } from "lucide-react";
import { useSip } from "../hooks/useSip";
import { agentsApi } from "../lib/api";
import type { SipConfig } from "../lib/sipClient";

interface Props {
  agentUsername: string;
  agentPassword: string;
}

export function Softphone({ agentUsername, agentPassword }: Props) {
  const [sipConfig, setSipConfig] = useState<SipConfig | null>(null);
  const [dialInput, setDialInput] = useState("");
  const [muted, setMuted] = useState(false);

  const { registered, callState, call, answer, hangup, hold, unhold, dtmf } = useSip(sipConfig);

  useEffect(() => {
    agentsApi.getTurnCredentials().then((creds) => {
      setSipConfig({
        wsUri: import.meta.env.VITE_FS_WSS ?? "wss://localhost:7443",
        domain: import.meta.env.VITE_FS_DOMAIN ?? "localhost",
        username: agentUsername,
        password: agentPassword,
        iceServers: [
          { urls: creds.urls, username: creds.username, credential: creds.credential },
        ],
        displayName: agentUsername,
      });
    });
  }, [agentUsername, agentPassword]);

  const statusColor = registered ? "bg-green-500" : "bg-red-500";
  const statusLabel = registered ? "Registered" : "Unregistered";

  return (
    <div className="bg-gray-900 text-white rounded-xl p-4 w-72 shadow-xl select-none">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <span className="font-semibold text-sm">{agentUsername}</span>
        <span className="flex items-center gap-1.5 text-xs">
          <span className={`w-2 h-2 rounded-full ${statusColor}`} />
          {statusLabel}
        </span>
      </div>

      {/* Call state banner */}
      {callState !== "idle" && (
        <div className="text-center text-sm py-1.5 mb-3 rounded bg-gray-800 font-mono tracking-wide">
          {callState === "calling" && "Dialing…"}
          {callState === "ringing" && "Incoming call"}
          {callState === "in_call" && "In call"}
          {callState === "hold" && "On hold"}
        </div>
      )}

      {/* Dial input */}
      <input
        type="tel"
        placeholder="+91…"
        value={dialInput}
        onChange={(e) => setDialInput(e.target.value)}
        className="w-full bg-gray-800 rounded px-3 py-2 text-sm mb-3 outline-none focus:ring-1 focus:ring-blue-500"
        disabled={callState !== "idle"}
      />

      {/* DTMF pad */}
      <div className="grid grid-cols-3 gap-1.5 mb-3">
        {["1","2","3","4","5","6","7","8","9","*","0","#"].map((k) => (
          <button
            key={k}
            onClick={() => {
              setDialInput((p) => p + k);
              if (callState === "in_call") dtmf(k);
            }}
            className="py-2 rounded bg-gray-700 hover:bg-gray-600 text-sm font-mono transition-colors"
          >
            {k}
          </button>
        ))}
      </div>

      {/* Action buttons */}
      <div className="flex gap-2">
        {callState === "idle" && (
          <button
            onClick={() => dialInput && call(dialInput)}
            disabled={!registered || !dialInput}
            className="flex-1 flex items-center justify-center gap-2 py-2 bg-green-600 hover:bg-green-500 disabled:opacity-40 rounded-lg text-sm transition-colors"
          >
            <Phone size={16} /> Call
          </button>
        )}

        {callState === "ringing" && (
          <>
            <button
              onClick={answer}
              className="flex-1 flex items-center justify-center gap-2 py-2 bg-green-600 hover:bg-green-500 rounded-lg text-sm transition-colors"
            >
              <PhoneIncoming size={16} /> Answer
            </button>
            <button
              onClick={hangup}
              className="flex-1 flex items-center justify-center gap-2 py-2 bg-red-600 hover:bg-red-500 rounded-lg text-sm transition-colors"
            >
              <PhoneOff size={16} /> Decline
            </button>
          </>
        )}

        {(callState === "in_call" || callState === "hold") && (
          <>
            <button
              onClick={callState === "hold" ? unhold : hold}
              className="flex-1 flex items-center justify-center gap-2 py-2 bg-yellow-600 hover:bg-yellow-500 rounded-lg text-sm transition-colors"
            >
              {callState === "hold" ? <Play size={16} /> : <Pause size={16} />}
              {callState === "hold" ? "Resume" : "Hold"}
            </button>
            <button
              onClick={hangup}
              className="flex-1 flex items-center justify-center gap-2 py-2 bg-red-600 hover:bg-red-500 rounded-lg text-sm transition-colors"
            >
              <PhoneOff size={16} /> End
            </button>
          </>
        )}

        {callState === "calling" && (
          <button
            onClick={hangup}
            className="flex-1 flex items-center justify-center gap-2 py-2 bg-red-600 hover:bg-red-500 rounded-lg text-sm transition-colors"
          >
            <PhoneOff size={16} /> Cancel
          </button>
        )}
      </div>
    </div>
  );
}

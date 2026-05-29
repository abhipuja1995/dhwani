/**
 * JsSIP WebRTC softphone client.
 *
 * Usage:
 *   const sip = new SipClient(config);
 *   await sip.start();
 *   sip.onIncoming = (session) => { ... };
 *   sip.call("+919876543210");
 */
import JsSIP from "jssip";

export interface SipConfig {
  wsUri: string;        // wss://freeswitch-host:7443
  domain: string;       // FreeSWITCH domain
  username: string;     // agent_001
  password: string;
  iceServers: RTCIceServer[];
  displayName?: string;
}

export type CallState = "idle" | "calling" | "ringing" | "in_call" | "hold";

export class SipClient {
  private ua: JsSIP.UA | null = null;
  private session: JsSIP.RTCSession | null = null;
  private remoteAudio: HTMLAudioElement;
  public state: CallState = "idle";

  onStateChange?: (state: CallState) => void;
  onIncoming?: (session: JsSIP.RTCSession) => void;
  onRegistered?: () => void;
  onUnregistered?: () => void;

  constructor(private config: SipConfig) {
    this.remoteAudio = new Audio();
    this.remoteAudio.autoplay = true;
  }

  start() {
    JsSIP.debug.enable("JsSIP:*");

    const socket = new JsSIP.WebSocketInterface(this.config.wsUri);
    this.ua = new JsSIP.UA({
      sockets: [socket],
      uri: `sip:${this.config.username}@${this.config.domain}`,
      password: this.config.password,
      display_name: this.config.displayName ?? this.config.username,
      register: true,
      register_expires: 300,
    });

    this.ua.on("registered", () => {
      console.log("[SIP] Registered");
      this.onRegistered?.();
    });

    this.ua.on("unregistered", () => {
      console.log("[SIP] Unregistered");
      this.onUnregistered?.();
    });

    this.ua.on("newRTCSession", ({ session }: { session: JsSIP.RTCSession }) => {
      if (session.direction === "incoming") {
        this.session = session;
        this._setState("ringing");
        this._wireSession(session);
        this.onIncoming?.(session);
      }
    });

    this.ua.start();
  }

  stop() {
    this.ua?.stop();
    this.ua = null;
  }

  call(target: string) {
    if (!this.ua || this.state !== "idle") return;

    const session = this.ua.call(`sip:${target}@${this.config.domain}`, {
      mediaConstraints: { audio: true, video: false },
      pcConfig: { iceServers: this.config.iceServers },
      rtcOfferConstraints: { offerToReceiveAudio: true, offerToReceiveVideo: false },
    }) as JsSIP.RTCSession;

    this.session = session;
    this._setState("calling");
    this._wireSession(session);
  }

  answer() {
    if (!this.session || this.state !== "ringing") return;
    this.session.answer({
      mediaConstraints: { audio: true, video: false },
      pcConfig: { iceServers: this.config.iceServers },
    });
  }

  hangup() {
    if (!this.session) return;
    try {
      this.session.terminate();
    } catch (_) {}
    this.session = null;
    this._setState("idle");
  }

  hold() {
    if (!this.session || this.state !== "in_call") return;
    this.session.hold();
    this._setState("hold");
  }

  unhold() {
    if (!this.session || this.state !== "hold") return;
    this.session.unhold();
    this._setState("in_call");
  }

  sendDtmf(tone: string) {
    this.session?.sendDTMF(tone);
  }

  private _wireSession(session: JsSIP.RTCSession) {
    session.on("accepted", () => this._setState("in_call"));
    session.on("confirmed", () => this._setState("in_call"));
    session.on("ended", () => {
      this.session = null;
      this._setState("idle");
    });
    session.on("failed", () => {
      this.session = null;
      this._setState("idle");
    });
    session.on("peerconnection", ({ peerconnection: pc }: { peerconnection: RTCPeerConnection }) => {
      pc.addEventListener("track", (e) => {
        const stream = e.streams[0];
        if (stream) this.remoteAudio.srcObject = stream;
      });
    });
  }

  private _setState(state: CallState) {
    this.state = state;
    this.onStateChange?.(state);
  }
}

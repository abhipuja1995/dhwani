import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Softphone } from "./components/Softphone";
import { CampaignPanel } from "./components/CampaignPanel";
import { Phone, LayoutDashboard } from "lucide-react";

const qc = new QueryClient();

function App() {
  const [agentCreds, setAgentCreds] = useState<{ username: string; password: string } | null>(null);
  const [loginForm, setLoginForm] = useState({ username: "agent_001", password: "agent001pass" });

  if (!agentCreds) {
    return (
      <div className="min-h-screen bg-gray-100 flex items-center justify-center">
        <div className="bg-white rounded-xl shadow p-8 w-80">
          <div className="flex items-center gap-2 mb-6">
            <Phone size={24} className="text-blue-600" />
            <h1 className="text-xl font-bold">Dialer Agent Login</h1>
          </div>
          <input className="w-full border rounded px-3 py-2 mb-3 text-sm" placeholder="Agent username" value={loginForm.username} onChange={(e) => setLoginForm({ ...loginForm, username: e.target.value })} />
          <input type="password" className="w-full border rounded px-3 py-2 mb-4 text-sm" placeholder="Password" value={loginForm.password} onChange={(e) => setLoginForm({ ...loginForm, password: e.target.value })} />
          <button onClick={() => setAgentCreds(loginForm)} className="w-full bg-blue-600 text-white py-2 rounded-lg hover:bg-blue-500 text-sm font-medium">
            Sign In
          </button>
        </div>
      </div>
    );
  }

  return (
    <QueryClientProvider client={qc}>
      <div className="min-h-screen bg-gray-100">
        {/* Topbar */}
        <header className="bg-white shadow-sm px-6 py-3 flex items-center gap-3">
          <Phone size={20} className="text-blue-600" />
          <span className="font-bold text-gray-800">Dialer</span>
          <span className="text-xs text-gray-400 ml-2">Outbound Call Center</span>
          <span className="ml-auto text-sm text-gray-600">{agentCreds.username}</span>
          <button onClick={() => setAgentCreds(null)} className="text-xs text-red-500 hover:underline ml-3">Sign out</button>
        </header>

        <main className="max-w-5xl mx-auto py-6 px-4 grid grid-cols-[280px_1fr] gap-6">
          {/* Left: softphone */}
          <div className="space-y-4">
            <Softphone agentUsername={agentCreds.username} agentPassword={agentCreds.password} />

            {/* Quick connectivity tests */}
            <div className="bg-white rounded-xl shadow p-3 text-xs space-y-1">
              <p className="font-medium text-gray-600 mb-2">Test calls (WiFi)</p>
              <button onClick={() => {}} className="block text-blue-600 hover:underline">→ 9196 (Echo test)</button>
              <button onClick={() => {}} className="block text-blue-600 hover:underline">→ 9197 (Milliwatt tone)</button>
              <button onClick={() => {}} className="block text-blue-600 hover:underline">→ agent_002 (Agent-to-agent)</button>
            </div>
          </div>

          {/* Right: campaign manager */}
          <div>
            <div className="flex items-center gap-2 mb-4">
              <LayoutDashboard size={18} className="text-gray-500" />
              <h2 className="font-semibold text-gray-700">Campaign Manager</h2>
            </div>
            <CampaignPanel />
          </div>
        </main>
      </div>
    </QueryClientProvider>
  );
}

export default App;

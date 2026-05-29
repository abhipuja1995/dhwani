import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Play, Pause, Plus, Upload } from "lucide-react";
import { campaignsApi } from "../lib/api";

export function CampaignPanel() {
  const qc = useQueryClient();
  const { data: campaigns = [] } = useQuery({ queryKey: ["campaigns"], queryFn: campaignsApi.list, refetchInterval: 5000 });

  const startMut = useMutation({ mutationFn: (id: string) => campaignsApi.start(id), onSuccess: () => qc.invalidateQueries({ queryKey: ["campaigns"] }) });
  const pauseMut = useMutation({ mutationFn: (id: string) => campaignsApi.pause(id), onSuccess: () => qc.invalidateQueries({ queryKey: ["campaigns"] }) });

  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ name: "", dial_mode: "progressive", dial_ratio: 1.5, caller_id: "" });

  const createMut = useMutation({
    mutationFn: () => campaignsApi.create(form),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["campaigns"] }); setShowCreate(false); },
  });

  const statusColor: Record<string, string> = {
    draft: "bg-gray-500", active: "bg-green-500", paused: "bg-yellow-500",
    completed: "bg-blue-500", cancelled: "bg-red-500",
  };

  return (
    <div className="bg-white rounded-xl shadow p-4">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold">Campaigns</h2>
        <button onClick={() => setShowCreate(true)} className="flex items-center gap-1 text-sm bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-500">
          <Plus size={14} /> New
        </button>
      </div>

      {/* Create form */}
      {showCreate && (
        <div className="mb-4 p-3 bg-gray-50 rounded-lg border text-sm">
          <input className="w-full border rounded px-2 py-1.5 mb-2" placeholder="Campaign name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <select className="w-full border rounded px-2 py-1.5 mb-2" value={form.dial_mode} onChange={(e) => setForm({ ...form, dial_mode: e.target.value })}>
            <option value="preview">Preview</option>
            <option value="progressive">Progressive</option>
            <option value="predictive">Predictive</option>
          </select>
          {form.dial_mode === "predictive" && (
            <input type="number" step="0.1" min="1" max="5" className="w-full border rounded px-2 py-1.5 mb-2" placeholder="Dial ratio (e.g. 1.5)" value={form.dial_ratio} onChange={(e) => setForm({ ...form, dial_ratio: parseFloat(e.target.value) })} />
          )}
          <input className="w-full border rounded px-2 py-1.5 mb-2" placeholder="Caller ID (optional)" value={form.caller_id} onChange={(e) => setForm({ ...form, caller_id: e.target.value })} />
          <div className="flex gap-2">
            <button onClick={() => createMut.mutate()} disabled={!form.name} className="flex-1 bg-blue-600 text-white py-1.5 rounded hover:bg-blue-500 disabled:opacity-40">Create</button>
            <button onClick={() => setShowCreate(false)} className="flex-1 border py-1.5 rounded hover:bg-gray-100">Cancel</button>
          </div>
        </div>
      )}

      {/* Campaign list */}
      <div className="space-y-2">
        {campaigns.map((c: any) => (
          <div key={c.id} className="flex items-center justify-between p-3 border rounded-lg hover:bg-gray-50">
            <div>
              <div className="flex items-center gap-2">
                <span className={`w-2 h-2 rounded-full ${statusColor[c.status] ?? "bg-gray-400"}`} />
                <span className="font-medium text-sm">{c.name}</span>
                <span className="text-xs text-gray-500 bg-gray-100 px-1.5 py-0.5 rounded">{c.dial_mode}</span>
              </div>
              <div className="text-xs text-gray-500 mt-0.5 ml-4">
                {c.dialed ?? 0} dialed · {c.answered ?? 0} answered · drop {((c.current_drop_rate ?? 0) * 100).toFixed(1)}%
              </div>
            </div>
            <div className="flex items-center gap-1.5">
              <ContactUpload campaignId={c.id} />
              {c.status === "active"
                ? <button onClick={() => pauseMut.mutate(c.id)} className="p-1.5 rounded hover:bg-yellow-100 text-yellow-600"><Pause size={14} /></button>
                : c.status !== "completed" && <button onClick={() => startMut.mutate(c.id)} className="p-1.5 rounded hover:bg-green-100 text-green-600"><Play size={14} /></button>
              }
            </div>
          </div>
        ))}
        {campaigns.length === 0 && <p className="text-sm text-gray-400 text-center py-4">No campaigns yet</p>}
      </div>
    </div>
  );
}

function ContactUpload({ campaignId }: { campaignId: string }) {
  const qc = useQueryClient();
  const mut = useMutation({ mutationFn: (f: File) => campaignsApi.uploadContacts(campaignId, f), onSuccess: () => qc.invalidateQueries({ queryKey: ["campaigns"] }) });

  return (
    <label className="cursor-pointer p-1.5 rounded hover:bg-blue-100 text-blue-600" title="Upload contacts CSV">
      <Upload size={14} />
      <input type="file" accept=".csv" className="hidden" onChange={(e) => e.target.files?.[0] && mut.mutate(e.target.files[0])} />
    </label>
  );
}

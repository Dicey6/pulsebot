import { supabase } from "@/lib/supabase";
import GenerateCodeButton from "./GenerateCodeButton";

async function getCodes() {
  const { data } = await supabase
    .from("invitation_codes")
    .select("*")
    .order("created_at", { ascending: false });
  return data || [];
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    unused: "bg-blue-900/40 text-blue-400",
    used: "bg-green-900/40 text-green-400",
    revoked: "bg-red-900/40 text-red-400",
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full ${colors[status] ?? "text-gray-400"}`}>
      {status}
    </span>
  );
}

export default async function CodesPage() {
  const codes = await getCodes();
  const unused = codes.filter((c: any) => c.status === "unused").length;

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Invitation Codes</h1>
          <p className="text-sm text-gray-500 mt-0.5">{unused} unused code(s) available</p>
        </div>
        <GenerateCodeButton />
      </div>

      <div className="bg-pulse-card border border-pulse-border rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="border-b border-pulse-border">
            <tr className="text-gray-500">
              <th className="text-left px-4 py-3">Code</th>
              <th className="text-left px-4 py-3">Starting Balance</th>
              <th className="text-left px-4 py-3">Status</th>
              <th className="text-left px-4 py-3">Assigned To</th>
              <th className="text-left px-4 py-3">Created</th>
              <th className="text-left px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {codes.map((c: any) => (
              <tr key={c.id} className="border-b border-pulse-border/50">
                <td className="px-4 py-3 font-mono text-white">{c.code}</td>
                <td className="px-4 py-3 text-gray-300">
                  {parseFloat(c.starting_balance_sol).toFixed(2)} SOL
                </td>
                <td className="px-4 py-3">
                  <StatusBadge status={c.status} />
                </td>
                <td className="px-4 py-3 text-gray-500 text-xs">
                  {c.assigned_telegram_id ?? "—"}
                </td>
                <td className="px-4 py-3 text-gray-500 text-xs">
                  {new Date(c.created_at).toLocaleDateString()}
                </td>
                <td className="px-4 py-3">
                  {c.status === "unused" && (
                    <form action="/api/codes" method="POST">
                      <input type="hidden" name="action" value="revoke" />
                      <input type="hidden" name="id" value={c.id} />
                      <button className="text-xs text-red-400 hover:text-red-300 hover:underline">
                        Revoke
                      </button>
                    </form>
                  )}
                </td>
              </tr>
            ))}
            {codes.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-gray-500">
                  No codes yet. Generate your first one.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

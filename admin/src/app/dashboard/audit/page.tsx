import { supabase } from "@/lib/supabase";

async function getLogs(page = 0) {
  const limit = 50;
  const { data, count } = await supabase
    .from("admin_audit_log")
    .select("*", { count: "exact" })
    .order("created_at", { ascending: false })
    .range(page * limit, page * limit + limit - 1);
  return { logs: data || [], count: count ?? 0 };
}

const ACTION_COLORS: Record<string, string> = {
  ban: "text-red-400",
  revoke_code: "text-red-400",
  pause: "text-yellow-400",
  restrict: "text-orange-400",
  activate: "text-green-400",
  set_balance: "text-blue-400",
  generate_code: "text-purple-400",
  force_close_position: "text-orange-400",
};

export default async function AuditPage({
  searchParams,
}: {
  searchParams: { page?: string };
}) {
  const page = parseInt(searchParams.page ?? "0", 10);
  const { logs, count } = await getLogs(page);
  const totalPages = Math.ceil(count / 50);

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-white">Audit Log</h1>
        <span className="text-sm text-gray-500">{count} total entries</span>
      </div>

      <div className="bg-pulse-card border border-pulse-border rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="border-b border-pulse-border">
            <tr className="text-gray-500">
              <th className="text-left px-4 py-3">Time</th>
              <th className="text-left px-4 py-3">Admin</th>
              <th className="text-left px-4 py-3">Action</th>
              <th className="text-left px-4 py-3">Target</th>
              <th className="text-left px-4 py-3">Details</th>
            </tr>
          </thead>
          <tbody>
            {logs.map((log: any) => (
              <tr key={log.id} className="border-b border-pulse-border/40">
                <td className="px-4 py-3 text-gray-500 text-xs whitespace-nowrap">
                  {new Date(log.created_at).toLocaleString()}
                </td>
                <td className="px-4 py-3 text-white">{log.admin_username}</td>
                <td className="px-4 py-3">
                  <span
                    className={`font-mono text-xs ${ACTION_COLORS[log.action] ?? "text-gray-300"}`}
                  >
                    {log.action}
                  </span>
                </td>
                <td className="px-4 py-3 text-gray-500 text-xs font-mono">
                  {log.target_user_id ? log.target_user_id.slice(0, 8) + "…" : "—"}
                </td>
                <td className="px-4 py-3 text-gray-600 text-xs font-mono">
                  {Object.keys(log.details || {}).length > 0
                    ? JSON.stringify(log.details)
                    : "—"}
                </td>
              </tr>
            ))}
            {logs.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-gray-500">
                  No audit entries yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div className="flex gap-2 text-sm">
          {page > 0 && (
            <a
              href={`?page=${page - 1}`}
              className="px-3 py-1.5 border border-pulse-border rounded-lg text-gray-400 hover:text-white transition"
            >
              ← Prev
            </a>
          )}
          <span className="px-3 py-1.5 text-gray-500">
            Page {page + 1} / {totalPages}
          </span>
          {page < totalPages - 1 && (
            <a
              href={`?page=${page + 1}`}
              className="px-3 py-1.5 border border-pulse-border rounded-lg text-gray-400 hover:text-white transition"
            >
              Next →
            </a>
          )}
        </div>
      )}
    </div>
  );
}

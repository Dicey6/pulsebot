"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export default function UserActions({
  userId,
  currentStatus,
}: {
  userId: string;
  currentStatus: string;
}) {
  const router = useRouter();
  const [loading, setLoading] = useState(false);

  async function doAction(action: string, extra?: Record<string, unknown>) {
    setLoading(true);
    await fetch(`/api/users/${userId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, ...extra }),
    });
    setLoading(false);
    router.refresh();
  }

  async function setBalance() {
    const raw = prompt("New SOL balance:");
    if (!raw) return;
    const val = parseFloat(raw);
    if (isNaN(val) || val < 0) return alert("Invalid balance");
    await doAction("set_balance", { balance: val });
  }

  const btnClass =
    "text-xs px-2 py-1 rounded border border-pulse-border hover:border-pulse-purple text-gray-400 hover:text-white transition disabled:opacity-40";

  return (
    <div className="flex gap-1 flex-wrap">
      <button className={btnClass} disabled={loading} onClick={() => doAction("pause")}>
        Pause
      </button>
      <button className={btnClass} disabled={loading} onClick={() => doAction("restrict")}>
        Restrict
      </button>
      <button className={btnClass} disabled={loading} onClick={() => doAction("ban")}>
        Ban
      </button>
      {currentStatus !== "active" && (
        <button className={btnClass} disabled={loading} onClick={() => doAction("activate")}>
          Activate
        </button>
      )}
      <button className={btnClass} disabled={loading} onClick={setBalance}>
        Set Balance
      </button>
      <button
        className={btnClass}
        disabled={loading}
        onClick={() => doAction("force_close_all")}
      >
        Force Close All
      </button>
    </div>
  );
}

"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export default function GenerateCodeButton() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [balance, setBalance] = useState("5");

  async function generate() {
    setLoading(true);
    const res = await fetch("/api/codes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "generate", balance: parseFloat(balance) }),
    });
    const data = await res.json();
    setLoading(false);
    setShowModal(false);
    if (data.code) {
      alert(`Code generated: ${data.code}`);
    }
    router.refresh();
  }

  return (
    <>
      <button
        onClick={() => setShowModal(true)}
        className="bg-pulse-purple hover:bg-purple-700 text-white text-sm font-medium px-4 py-2 rounded-lg transition"
      >
        + Generate Code
      </button>

      {showModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-pulse-card border border-pulse-border rounded-xl p-6 w-80 space-y-4">
            <h2 className="text-white font-bold">Generate Invitation Code</h2>
            <div>
              <label className="text-sm text-gray-400 mb-1 block">Starting Balance (SOL)</label>
              <input
                type="number"
                min="0"
                step="0.1"
                value={balance}
                onChange={(e) => setBalance(e.target.value)}
                className="w-full bg-pulse-dark border border-pulse-border rounded-lg px-3 py-2 text-white focus:outline-none focus:border-pulse-purple"
              />
            </div>
            <div className="flex gap-3">
              <button
                onClick={generate}
                disabled={loading}
                className="flex-1 bg-pulse-purple hover:bg-purple-700 text-white font-medium py-2 rounded-lg text-sm transition disabled:opacity-60"
              >
                {loading ? "Generating…" : "Generate"}
              </button>
              <button
                onClick={() => setShowModal(false)}
                className="flex-1 border border-pulse-border text-gray-400 hover:text-white py-2 rounded-lg text-sm transition"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

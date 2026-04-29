"use client";

import { useState } from "react";
import { QuickConnectDialog } from "./QuickConnectDialog";

export function QuickConnectButton() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="rounded-md bg-accent text-bg font-medium px-3 py-1.5 text-sm hover:shadow-glow transition"
      >
        + Quick Connect
      </button>
      {open ? <QuickConnectDialog onClose={() => setOpen(false)} /> : null}
    </>
  );
}

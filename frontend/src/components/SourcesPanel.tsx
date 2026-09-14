import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { Source } from "../api/client";

export function SourcesPanel({ sources }: { sources: Source[] }) {
  const [open, setOpen] = useState(false);
  if (!sources.length) return null;
  return <div className="sources">
    <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}>
      {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />} Ver evidencia
    </button>
    {open && <div className="source-list">
      {sources.map((source, i) => <div className="source-item" key={i}>
        <strong>{source.source}</strong>
        <div className="source-meta">{source.seccion} · {source.tipo_fuente === "internal" ? "Interna" : "Externa"}</div>
        <p>{source.fragment}</p>
      </div>)}
    </div>}
  </div>;
}

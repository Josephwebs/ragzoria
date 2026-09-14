from langchain_core.documents import Document

def load_documents(settings):
    documents = []
    for kind in ("internal", "external"):
        for path in sorted((settings.data_dir / kind).glob("*")):
            if path.suffix.lower() not in {".md", ".txt"}:
                continue
            title, section, lines = "", "General", []

            def append_section():
                text = "\n".join(lines).strip()
                if text:
                    documents.append(Document(
                        page_content=f"{title}\n{section}\n{text}".strip(),
                        metadata={"source": path.name, "tipo_fuente": kind,
                                  "categoria": kind, "seccion": section},
                    ))

            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith("# "):
                    title = line[2:].strip()
                elif line.startswith(("## ", "### ")):
                    append_section()
                    section, lines = line.lstrip("# ").strip(), []
                else:
                    lines.append(line)
            append_section()
    return documents

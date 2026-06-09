function fmtQuillSegment(text: string, attrs: Record<string, unknown>): string {
  if (!text) return "";
  if (attrs.bold && attrs.italic) return `***${text}***`;
  if (attrs.bold) return `**${text}**`;
  if (attrs.italic) return `*${text}*`;
  return text;
}

export function quillDeltaToMd(raw: string | null | undefined): string {
  if (!raw || !String(raw).trim()) return "- (미입력)";
  const text = String(raw).trim();
  let ops: Array<{ insert?: unknown; attributes?: Record<string, unknown> }>;
  try {
    ops = JSON.parse(text).ops;
    if (!Array.isArray(ops)) return text;
  } catch {
    return text;
  }

  const linesOut: string[] = [];
  let pending = "";
  let olCounter = 0;

  const flushLine = (lineText: string, attrs: Record<string, unknown>) => {
    const header = attrs.header;
    const listAttr = attrs.list;
    if (header) {
      linesOut.push(`${"#".repeat(Number(header))} ${lineText}`);
      olCounter = 0;
    } else if (listAttr === "bullet") {
      linesOut.push(`- ${lineText}`);
      olCounter = 0;
    } else if (listAttr === "ordered") {
      olCounter += 1;
      linesOut.push(`${olCounter}. ${lineText}`);
    } else if (listAttr === "unchecked") {
      linesOut.push(`- [ ] ${lineText}`);
      olCounter = 0;
    } else if (listAttr === "checked") {
      linesOut.push(`- [x] ${lineText}`);
      olCounter = 0;
    } else {
      linesOut.push(lineText);
      olCounter = 0;
    }
  };

  for (const op of ops) {
    const insert = op.insert;
    if (typeof insert !== "string") continue;
    const attrs = op.attributes ?? {};
    if (!insert.includes("\n")) {
      pending += fmtQuillSegment(insert, attrs);
      continue;
    }
    const chunks = insert.split("\n");
    chunks.forEach((chunk, idx) => {
      if (chunk) pending += fmtQuillSegment(chunk, idx === 0 ? attrs : {});
      if (idx < chunks.length - 1) {
        flushLine(pending, attrs);
        pending = "";
      }
    });
  }
  if (pending) flushLine(pending, {});
  const result = linesOut.join("\n").trim();
  return result || "- (미입력)";
}

export function quillDeltaFirstLine(raw: string | null | undefined): string {
  const md = quillDeltaToMd(raw);
  if (md === "- (미입력)") return "—";
  const first = md.split("\n")[0]?.trim();
  return first || "—";
}

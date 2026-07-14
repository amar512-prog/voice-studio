const textDecoder = new TextDecoder();
const textEncoder = new TextEncoder();

function getAttr(tag, name) {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = tag.match(new RegExp(`\\s${escaped}="([^"]*)"`, "i"));
  return match ? decodeXml(match[1]) : "";
}

function decodeXml(value) {
  return String(value || "")
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">")
    .replaceAll("&quot;", "\"")
    .replaceAll("&apos;", "'")
    .replaceAll("&amp;", "&");
}

function escapeXml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll("\"", "&quot;")
    .replaceAll("'", "&apos;");
}

function normalizeZipPath(basePath, target) {
  if (!target) return "";
  if (target.startsWith("/")) return target.slice(1);
  const stack = basePath.split("/").filter(Boolean);
  target.split("/").forEach((part) => {
    if (!part || part === ".") return;
    if (part === "..") stack.pop();
    else stack.push(part);
  });
  return stack.join("/");
}

function findEndOfCentralDirectory(bytes) {
  for (let offset = bytes.length - 22; offset >= Math.max(0, bytes.length - 66000); offset -= 1) {
    if (
      bytes[offset] === 0x50 &&
      bytes[offset + 1] === 0x4b &&
      bytes[offset + 2] === 0x05 &&
      bytes[offset + 3] === 0x06
    ) {
      return offset;
    }
  }
  throw new Error("Could not read this workbook. Save it as a standard .xlsx file and try again.");
}

async function inflateZipEntry(entry) {
  if (entry.method === 0) return entry.data;
  if (entry.method !== 8) {
    throw new Error("This workbook uses an unsupported Excel compression method.");
  }
  if (typeof DecompressionStream === "undefined") {
    throw new Error("This browser cannot read compressed .xlsx files. Re-save the file in Excel or Chrome and try again.");
  }
  const stream = new Blob([entry.data]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

async function readZipEntries(file) {
  const bytes = new Uint8Array(await file.arrayBuffer());
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const eocdOffset = findEndOfCentralDirectory(bytes);
  const totalEntries = view.getUint16(eocdOffset + 10, true);
  let offset = view.getUint32(eocdOffset + 16, true);
  const entries = new Map();

  for (let index = 0; index < totalEntries; index += 1) {
    if (view.getUint32(offset, true) !== 0x02014b50) {
      throw new Error("Could not read the workbook file list.");
    }
    const method = view.getUint16(offset + 10, true);
    const compressedSize = view.getUint32(offset + 20, true);
    const nameLength = view.getUint16(offset + 28, true);
    const extraLength = view.getUint16(offset + 30, true);
    const commentLength = view.getUint16(offset + 32, true);
    const localOffset = view.getUint32(offset + 42, true);
    const nameStart = offset + 46;
    const name = textDecoder.decode(bytes.slice(nameStart, nameStart + nameLength));

    if (view.getUint32(localOffset, true) !== 0x04034b50) {
      throw new Error("Could not read the workbook sheet data.");
    }
    const localNameLength = view.getUint16(localOffset + 26, true);
    const localExtraLength = view.getUint16(localOffset + 28, true);
    const dataStart = localOffset + 30 + localNameLength + localExtraLength;
    const data = bytes.slice(dataStart, dataStart + compressedSize);
    entries.set(name, { method, data });
    offset = nameStart + nameLength + extraLength + commentLength;
  }
  return entries;
}

async function zipText(entries, path) {
  const entry = entries.get(path);
  if (!entry) return "";
  return textDecoder.decode(await inflateZipEntry(entry));
}

function firstSheetPath(workbookXml, relsXml) {
  const sheetTag = workbookXml.match(/<sheet\b[^>]*>/i)?.[0] || "";
  const relationshipId = getAttr(sheetTag, "r:id");
  if (!relationshipId) return "xl/worksheets/sheet1.xml";

  const relationships = relsXml.match(/<Relationship\b[^>]*>/gi) || [];
  const relationship = relationships.find((tag) => getAttr(tag, "Id") === relationshipId);
  return normalizeZipPath("xl", getAttr(relationship || "", "Target")) || "xl/worksheets/sheet1.xml";
}

function parseSharedStrings(sharedStringsXml) {
  if (!sharedStringsXml) return [];
  return (sharedStringsXml.match(/<si\b[\s\S]*?<\/si>/gi) || []).map((item) => {
    const textParts = [...item.matchAll(/<t\b[^>]*>([\s\S]*?)<\/t>/gi)].map((match) => decodeXml(match[1]));
    return textParts.join("");
  });
}

function parseCellValue(cellTag, cellBody, sharedStrings) {
  const type = getAttr(cellTag, "t");
  if (type === "inlineStr") {
    return [...cellBody.matchAll(/<t\b[^>]*>([\s\S]*?)<\/t>/gi)]
      .map((match) => decodeXml(match[1]))
      .join("");
  }
  const rawValue = cellBody.match(/<v\b[^>]*>([\s\S]*?)<\/v>/i)?.[1] || "";
  if (type === "s") return sharedStrings[Number(rawValue)] || "";
  return decodeXml(rawValue);
}

function firstColumnTexts(sheetXml, sharedStrings) {
  const rows = sheetXml.match(/<row\b[^>]*>[\s\S]*?<\/row>/gi) || [];
  const values = [];
  rows.forEach((rowXml) => {
    const cells = [...rowXml.matchAll(/<c\b([^>]*)>([\s\S]*?)<\/c>/gi)];
    if (cells.length === 0) return;
    const firstColumnCell =
      cells.find((match) => /^A\d*$/i.test(getAttr(`<c ${match[1]}>`, "r"))) || cells[0];
    const value = parseCellValue(`<c ${firstColumnCell[1]}>`, firstColumnCell[2], sharedStrings).trim();
    if (value) values.push(value);
  });
  return values[0]?.toLowerCase() === "text" ? values.slice(1) : values;
}

export async function extractFirstColumnTexts(file) {
  const entries = await readZipEntries(file);
  const workbookXml = await zipText(entries, "xl/workbook.xml");
  const relsXml = await zipText(entries, "xl/_rels/workbook.xml.rels");
  const sharedStrings = parseSharedStrings(await zipText(entries, "xl/sharedStrings.xml"));
  const sheetPath = firstSheetPath(workbookXml, relsXml);
  const sheetXml = await zipText(entries, sheetPath);
  const values = firstColumnTexts(sheetXml, sharedStrings);
  if (values.length === 0) {
    throw new Error("The first sheet must contain text in the first column.");
  }
  return values;
}

function crc32(bytes) {
  if (!crc32.table) {
    crc32.table = Array.from({ length: 256 }, (_, index) => {
      let value = index;
      for (let bit = 0; bit < 8; bit += 1) {
        value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
      }
      return value >>> 0;
    });
  }
  let crc = 0xffffffff;
  bytes.forEach((byte) => {
    crc = crc32.table[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  });
  return (crc ^ 0xffffffff) >>> 0;
}

function pushUint16(target, value) {
  target.push(value & 0xff, (value >>> 8) & 0xff);
}

function pushUint32(target, value) {
  target.push(value & 0xff, (value >>> 8) & 0xff, (value >>> 16) & 0xff, (value >>> 24) & 0xff);
}

function buildZip(files) {
  const chunks = [];
  const centralDirectory = [];
  let offset = 0;

  files.forEach(({ path, content }) => {
    const nameBytes = textEncoder.encode(path);
    const dataBytes = textEncoder.encode(content);
    const crc = crc32(dataBytes);
    const localHeader = [];
    pushUint32(localHeader, 0x04034b50);
    pushUint16(localHeader, 20);
    pushUint16(localHeader, 0);
    pushUint16(localHeader, 0);
    pushUint16(localHeader, 0);
    pushUint16(localHeader, 0);
    pushUint32(localHeader, crc);
    pushUint32(localHeader, dataBytes.length);
    pushUint32(localHeader, dataBytes.length);
    pushUint16(localHeader, nameBytes.length);
    pushUint16(localHeader, 0);
    chunks.push(new Uint8Array(localHeader), nameBytes, dataBytes);

    const centralHeader = [];
    pushUint32(centralHeader, 0x02014b50);
    pushUint16(centralHeader, 20);
    pushUint16(centralHeader, 20);
    pushUint16(centralHeader, 0);
    pushUint16(centralHeader, 0);
    pushUint16(centralHeader, 0);
    pushUint16(centralHeader, 0);
    pushUint32(centralHeader, crc);
    pushUint32(centralHeader, dataBytes.length);
    pushUint32(centralHeader, dataBytes.length);
    pushUint16(centralHeader, nameBytes.length);
    pushUint16(centralHeader, 0);
    pushUint16(centralHeader, 0);
    pushUint16(centralHeader, 0);
    pushUint16(centralHeader, 0);
    pushUint32(centralHeader, 0);
    pushUint32(centralHeader, offset);
    centralDirectory.push(new Uint8Array(centralHeader), nameBytes);
    offset += localHeader.length + nameBytes.length + dataBytes.length;
  });

  const centralOffset = offset;
  const centralSize = centralDirectory.reduce((sum, chunk) => sum + chunk.length, 0);
  const end = [];
  pushUint32(end, 0x06054b50);
  pushUint16(end, 0);
  pushUint16(end, 0);
  pushUint16(end, files.length);
  pushUint16(end, files.length);
  pushUint32(end, centralSize);
  pushUint32(end, centralOffset);
  pushUint16(end, 0);

  return new Blob([...chunks, ...centralDirectory, new Uint8Array(end)], {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
  });
}

function inlineCell(rowIndex, columnIndex, value) {
  const column = String.fromCharCode("A".charCodeAt(0) + columnIndex);
  return `<c r="${column}${rowIndex}" t="inlineStr"><is><t>${escapeXml(value)}</t></is></c>`;
}

function worksheetXml(rows) {
  const sheetRows = rows
    .map((row, rowIndex) => {
      const excelRow = rowIndex + 1;
      const cells = row.map((value, columnIndex) => inlineCell(excelRow, columnIndex, value)).join("");
      return `<row r="${excelRow}">${cells}</row>`;
    })
    .join("");
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheetData>${sheetRows}</sheetData>
</worksheet>`;
}

export function buildBatchWorkbookFile({
  texts,
  voice,
  speechContext,
  targetSeconds,
  wpm,
  exportM4a,
  enhanceText,
}) {
  const headers = [
    "text",
    "voice_id",
    "voice_name",
    "accent",
    "speech_context",
    "target_seconds",
    "wpm",
    "export_m4a",
    "enhance_text",
  ];
  const rows = [
    headers,
    ...texts.map((text) => [
      text,
      voice.voice_id,
      voice.voice_name || "",
      voice.accent || "auto",
      speechContext,
      String(targetSeconds || 55),
      String(wpm || 135),
      exportM4a ? "true" : "false",
      enhanceText ? "true" : "false",
    ]),
  ];

  const workbook = buildZip([
    {
      path: "[Content_Types].xml",
      content: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>`,
    },
    {
      path: "_rels/.rels",
      content: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>`,
    },
    {
      path: "xl/workbook.xml",
      content: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="tts_requests" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>`,
    },
    {
      path: "xl/_rels/workbook.xml.rels",
      content: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>`,
    },
    {
      path: "xl/worksheets/sheet1.xml",
      content: worksheetXml(rows),
    },
  ]);
  return new File([workbook], "tts_requests.xlsx", { type: workbook.type });
}

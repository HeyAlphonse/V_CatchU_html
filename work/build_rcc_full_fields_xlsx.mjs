import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";


const [csvPath, outputPath, previewPath, inspectPath, expectedRowsRaw] = process.argv.slice(2);
if (!csvPath || !outputPath || !previewPath || !inspectPath) {
  throw new Error("Usage: build_rcc_full_fields_xlsx.mjs input.csv output.xlsx preview.png inspect.ndjson [expectedRows]");
}

const headers = ["ID", "项目名称", "省份", "城市", "项目阶段", "造价", "总投资额", "更新时间"];
const expectedRows = expectedRowsRaw ? Number(expectedRowsRaw) : null;

function parseCsv(text) {
  const rows = [];
  let row = [];
  let value = "";
  let inQuotes = false;
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    const next = text[index + 1];
    if (inQuotes) {
      if (character === '"' && next === '"') {
        value += '"';
        index += 1;
      } else if (character === '"') {
        inQuotes = false;
      } else {
        value += character;
      }
    } else if (character === '"') {
      inQuotes = true;
    } else if (character === ",") {
      row.push(value);
      value = "";
    } else if (character === "\n") {
      row.push(value);
      rows.push(row);
      row = [];
      value = "";
    } else if (character !== "\r") {
      value += character;
    }
  }
  if (value.length || row.length) {
    row.push(value);
    rows.push(row);
  }
  return rows.filter((candidate) => candidate.some((cell) => cell !== ""));
}

function parseNumber(value) {
  if (!value) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function parseChinaDateTime(value) {
  if (!value) return null;
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})$/);
  if (!match) return value;
  const [, year, month, day, hour, minute] = match;
  const milliseconds = Date.UTC(Number(year), Number(month) - 1, Number(day), Number(hour), Number(minute), 0);
  return milliseconds / 86_400_000 + 25_569;
}

let csvText = (await fs.readFile(csvPath, "utf8")).replace(/^\uFEFF/, "");
const csvRows = parseCsv(csvText);
const csvHeaders = csvRows[0] ?? [];
if (headers.some((header, index) => csvHeaders[index] !== header)) {
  throw new Error(`Unexpected CSV headers: ${JSON.stringify(csvHeaders)}`);
}

const records = csvRows.slice(1).map((row) => [
  row[0] || "", row[1] || "", row[2] || "", row[3] || "", row[4] || "",
  parseNumber(row[5]), parseNumber(row[6]), parseChinaDateTime(row[7]),
]);
if (expectedRows !== null && records.length !== expectedRows) {
  throw new Error(`Expected ${expectedRows} rows, found ${records.length}`);
}

const workbook = Workbook.create();
const sheet = workbook.worksheets.add("项目清单");
const matrix = [headers, ...records];
const lastRow = matrix.length;
const tableRange = `A1:H${lastRow}`;
sheet.getRange(tableRange).values = matrix;
sheet.showGridLines = false;
sheet.freezePanes.freezeRows(1);
sheet.freezePanes.freezeColumns(2);

const header = sheet.getRange("A1:H1");
header.format = { fill: "#174E5A", font: { bold: true, color: "#FFFFFF" } };
header.format.rowHeight = 24;
header.format.horizontalAlignment = "center";
header.format.verticalAlignment = "center";

sheet.getRange(`A2:A${lastRow}`).format.horizontalAlignment = "center";
sheet.getRange(`B2:B${lastRow}`).format.wrapText = true;
sheet.getRange(`B2:B${lastRow}`).format.verticalAlignment = "top";
sheet.getRange(`C2:E${lastRow}`).format.horizontalAlignment = "center";
sheet.getRange(`F2:G${lastRow}`).format.numberFormat = "#,##0.00";
sheet.getRange(`F2:G${lastRow}`).format.horizontalAlignment = "right";
sheet.getRange(`H2:H${lastRow}`).format.numberFormat = "yyyy-mm-dd hh:mm";
sheet.getRange(`H2:H${lastRow}`).format.horizontalAlignment = "center";

sheet.getRange("A:A").format.columnWidth = 12;
sheet.getRange("B:B").format.columnWidth = 80;
sheet.getRange("C:C").format.columnWidth = 12;
sheet.getRange("D:D").format.columnWidth = 18;
sheet.getRange("E:E").format.columnWidth = 16;
sheet.getRange("F:G").format.columnWidth = 14;
sheet.getRange("H:H").format.columnWidth = 20;

sheet.getRange(tableRange).format.borders = { preset: "outside", style: "thin", color: "#C9D3D8" };
const table = sheet.tables.add(tableRange, true, "RccProjectTable");
table.style = "TableStyleMedium2";
table.showFilterButton = true;

const tableInspect = await workbook.inspect({
  kind: "table", sheetId: "项目清单", range: `A1:H${Math.min(lastRow, 20)}`,
  tableMaxRows: 20, tableMaxCols: 8, maxChars: 6000,
});
const errorScan = await workbook.inspect({
  kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 }, summary: "formula error scan",
});
await fs.mkdir(path.dirname(inspectPath), { recursive: true });
await fs.writeFile(inspectPath, `${tableInspect.ndjson}\n${errorScan.ndjson}\n`, "utf8");

const preview = await workbook.render({ sheetName: "项目清单", range: `A1:H${Math.min(lastRow, 30)}`, scale: 1, format: "png" });
await fs.mkdir(path.dirname(previewPath), { recursive: true });
await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));
await fs.mkdir(path.dirname(outputPath), { recursive: true });
const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(outputPath);

console.log(JSON.stringify({ outputPath, previewPath, inspectPath, dataRowCount: records.length, sheetName: "项目清单", columns: headers.length }));

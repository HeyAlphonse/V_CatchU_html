import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


REQUIRED_FIELDS = ["ID", "项目名称", "省份", "城市", "项目阶段", "更新时间"]


@dataclass(frozen=True)
class Paths:
    root: Path
    code_root: Path

    @property
    def work_root(self) -> Path:
        return self.root / ".codex_work" / "rcc_web_capture"

    @property
    def sessions(self) -> Path:
        return self.work_root / "sessions"

    @property
    def active(self) -> Path:
        return self.work_root / "active_session.json"

    @property
    def builder(self) -> Path:
        return self.code_root / "work" / "build_rcc_full_fields_xlsx.mjs"


def utc_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def safe_label(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "-", value.strip()).strip("-")
    return cleaned[:40] or "rcc"


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def session_dir(paths: Paths, session_id: str) -> Path:
    return paths.sessions / session_id


def resolve_session(paths: Paths, explicit_session: str = "") -> tuple[str, Path, dict]:
    if explicit_session:
        session_id = explicit_session
    else:
        if not paths.active.exists():
            raise SystemExit("没有活动批次。请先运行 new。")
        session_id = load_json(paths.active).get("session_id", "")
    state_path = session_dir(paths, session_id) / "state.json"
    if not state_path.exists():
        raise SystemExit(f"找不到批次状态：{state_path}")
    return session_id, state_path, load_json(state_path)


def persist_state(paths: Paths, session_id: str, state: dict) -> None:
    state["updated_at"] = utc_now()
    save_json(session_dir(paths, session_id) / "state.json", state)


def emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def command_new(args, paths: Paths) -> None:
    if args.start_page < 1 or args.end_page < args.start_page:
        raise SystemExit("页码范围无效：开始页必须大于等于 1，结束页不得小于开始页。")
    session_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_label(args.label)}_p{args.start_page}-{args.end_page}"
    target = session_dir(paths, session_id)
    target.mkdir(parents=True, exist_ok=False)
    state = {
        "workflow": "rcc_web_capture_to_excel",
        "version": 1,
        "session_id": session_id,
        "status": "AWAITING_SETTINGS",
        "created_at": utc_now(),
        "start_page": args.start_page,
        "end_page": args.end_page,
        "requested_pages": list(range(args.start_page, args.end_page + 1)),
        "captured_pages": [],
        "next_expected_page": args.start_page,
        "schema": ["ID", "项目名称", "省份", "城市", "项目阶段", "造价", "总投资额", "更新时间"],
        "settings": None,
        "last_export": None,
    }
    persist_state(paths, session_id, state)
    save_json(paths.active, {"session_id": session_id, "updated_at": utc_now()})
    emit({
        "action": "new",
        "session_id": session_id,
        "status": state["status"],
        "page_range": [args.start_page, args.end_page],
        "next": "请在网页上核对筛选、排序、每页条数、当前页和下一页按钮，然后运行 confirm。",
    })


def command_confirm(args, paths: Paths) -> None:
    session_id, _, state = resolve_session(paths, args.session)
    if state["status"] not in {"AWAITING_SETTINGS", "READY"}:
        raise SystemExit(f"当前状态 {state['status']} 不允许重新确认网页设置。")
    if args.current_page != state["start_page"]:
        raise SystemExit(f"当前页应为起始页 {state['start_page']}，实际确认的是 {args.current_page}。")
    if args.page_size < 1:
        raise SystemExit("每页条数必须大于 0。")
    state["settings"] = {
        "confirmed_at": utc_now(),
        "current_page": args.current_page,
        "page_size": args.page_size,
        "page_title": args.page_title,
        "source_url": args.source_url,
        "filter_summary": args.filter_summary,
        "sort_summary": args.sort_summary,
        "next_button_verified": True,
    }
    state["status"] = "READY"
    persist_state(paths, session_id, state)
    emit({"action": "confirm", "session_id": session_id, "status": "READY", "next": "等待用户明确说“开始”。"})


def command_start(args, paths: Paths) -> None:
    session_id, _, state = resolve_session(paths, args.session)
    if state["status"] == "CAPTURING":
        emit({"action": "start", "session_id": session_id, "status": "CAPTURING", "next_expected_page": state["next_expected_page"], "idempotent": True})
        return
    if state["status"] != "READY":
        raise SystemExit(f"只有 READY 状态可以开始抓取；当前状态为 {state['status']}。")
    state["status"] = "CAPTURING"
    state["started_at"] = utc_now()
    persist_state(paths, session_id, state)
    emit({"action": "start", "session_id": session_id, "status": "CAPTURING", "next_expected_page": state["next_expected_page"]})


def read_page_input(args) -> str:
    if args.input:
        return Path(args.input).read_text(encoding="utf-8")
    if not sys.stdin.isatty():
        return sys.stdin.read()
    raise SystemExit("请通过 --input 指定页面文本文件，或从标准输入传入文本。")


def command_save_page(args, paths: Paths) -> None:
    session_id, _, state = resolve_session(paths, args.session)
    if state["status"] not in {"CAPTURING", "CAPTURED"}:
        raise SystemExit(f"当前状态 {state['status']} 不允许保存页面。")
    if args.page not in state["requested_pages"]:
        raise SystemExit(f"页码 {args.page} 不在本批范围内。")

    text = read_page_input(args).strip()
    if not text:
        raise SystemExit("页面文本为空，未保存。")

    sys.path.insert(0, str(paths.code_root / "work"))
    from parse_rcc_full_fields import parse_text

    parsed = parse_text(text, args.page)
    if not parsed:
        raise SystemExit("页面文本中没有识别到 6–8 位 RCC 项目 ID，未保存。")

    page_path = session_dir(paths, session_id) / "raw_pages" / f"page_{args.page:04d}.txt"
    metadata_path = session_dir(paths, session_id) / "page_metadata" / f"page_{args.page:04d}.json"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    captured = {item["page"]: item for item in state.get("captured_pages", [])}

    if args.page in captured:
        if captured[args.page]["sha256"] == digest:
            emit({"action": "save-page", "session_id": session_id, "page": args.page, "idempotent": True, "record_count": len(parsed)})
            return
        raise SystemExit("该页已经保存过不同内容。为避免覆盖审计记录，请创建新批次重抓。")

    if args.page != state["next_expected_page"]:
        raise SystemExit(f"必须按顺序保存。下一页应为 {state['next_expected_page']}，实际传入 {args.page}。")

    page_path.parent.mkdir(parents=True, exist_ok=True)
    page_path.write_text(text + "\n", encoding="utf-8")
    metadata = {
        "page": args.page,
        "saved_at": utc_now(),
        "source_url": args.source_url,
        "sha256": digest,
        "record_count": len(parsed),
        "first_id": parsed[0]["ID"],
        "last_id": parsed[-1]["ID"],
        "raw_text_path": str(page_path),
    }
    save_json(metadata_path, metadata)
    state.setdefault("captured_pages", []).append(metadata)
    state["captured_pages"].sort(key=lambda item: item["page"])
    remaining = [page for page in state["requested_pages"] if page not in {item["page"] for item in state["captured_pages"]}]
    if remaining:
        state["next_expected_page"] = remaining[0]
        state["status"] = "CAPTURING"
    else:
        state["next_expected_page"] = None
        state["status"] = "CAPTURED"
        state["captured_at"] = utc_now()
    state["last_export"] = None
    persist_state(paths, session_id, state)
    emit({
        "action": "save-page",
        "session_id": session_id,
        "page": args.page,
        "record_count": len(parsed),
        "first_id": parsed[0]["ID"],
        "last_id": parsed[-1]["ID"],
        "status": state["status"],
        "next_expected_page": state["next_expected_page"],
    })


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def codex_dependencies_root() -> Path:
    return Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies"


def resolve_node_executable(explicit: str = "") -> Path:
    runtime_root = codex_dependencies_root()
    candidates = [
        explicit,
        os.environ.get("RCC_NODE_EXE", ""),
        str(runtime_root / "node" / "bin" / ("node.exe" if os.name == "nt" else "node")),
        shutil.which("node") or "",
    ]
    for candidate in candidates:
        if candidate:
            path = Path(candidate).expanduser()
            if path.is_file():
                return path.resolve()
    raise SystemExit(
        "找不到 Node.js。请在 Codex 桌面版中运行，或使用 --node-exe / RCC_NODE_EXE 指定路径。"
    )


def resolve_node_modules(explicit: str = "") -> Path:
    runtime_root = codex_dependencies_root()
    candidates = [
        explicit,
        os.environ.get("RCC_NODE_MODULES", ""),
        str(runtime_root / "node" / "node_modules"),
    ]
    for candidate in candidates:
        if candidate:
            path = Path(candidate).expanduser()
            if (path / "@oai" / "artifact-tool" / "package.json").is_file():
                return path.resolve()
    raise SystemExit(
        "找不到 Codex Excel 导出依赖 @oai/artifact-tool。"
        "请在 Codex 桌面版中运行，或使用 --node-modules / RCC_NODE_MODULES 指定路径。"
    )


def ensure_node_modules(paths: Paths, node_modules: Path) -> None:
    junction = paths.code_root / "work" / "node_modules"
    if junction.exists():
        if not (junction / "@oai" / "artifact-tool" / "package.json").is_file():
            raise SystemExit(f"现有依赖目录不包含 @oai/artifact-tool：{junction}")
        return
    if not node_modules.exists():
        raise SystemExit(f"找不到工作区依赖：{node_modules}")
    if os.name == "nt":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(node_modules)],
            check=True,
            capture_output=True,
            text=True,
        )
    else:
        junction.symlink_to(node_modules, target_is_directory=True)


def command_doctor(args, paths: Paths) -> None:
    node_exe = resolve_node_executable(args.node_exe)
    node_modules = resolve_node_modules(args.node_modules)
    emit({
        "status": "OK",
        "python": sys.executable,
        "node": str(node_exe),
        "node_modules": str(node_modules),
        "excel_builder": str(paths.builder),
        "excel_builder_exists": paths.builder.is_file(),
    })


def command_export(args, paths: Paths) -> None:
    session_id, _, state = resolve_session(paths, args.session)
    missing_pages = [page for page in state["requested_pages"] if page not in {item["page"] for item in state.get("captured_pages", [])}]
    if missing_pages:
        raise SystemExit(f"页面尚未抓取完整，缺少：{missing_pages}")

    sys.path.insert(0, str(paths.code_root / "work"))
    from parse_rcc_full_fields import HEADERS, SOURCE_PAGE, dedupe_rows, parse_text

    all_rows = []
    per_page = []
    for page in state["requested_pages"]:
        page_path = session_dir(paths, session_id) / "raw_pages" / f"page_{page:04d}.txt"
        rows = parse_text(page_path.read_text(encoding="utf-8"), page)
        all_rows.extend(rows)
        per_page.append({"page": page, "rows": len(rows), "first_id": rows[0]["ID"] if rows else "", "last_id": rows[-1]["ID"] if rows else ""})

    deduped, dedupe_summary = dedupe_rows(all_rows)
    missing_fields = {field: sum(1 for row in deduped if not row.get(field, "").strip()) for field in REQUIRED_FIELDS}
    if any(missing_fields.values()) and not args.allow_incomplete_records:
        raise SystemExit(f"关键字段存在空值，已停止导出：{json.dumps(missing_fields, ensure_ascii=False)}")

    parsed_dir = session_dir(paths, session_id) / "parsed"
    csv_path = parsed_dir / "projects.csv"
    audit_csv_path = parsed_dir / "projects_with_source_page.csv"
    summary_path = parsed_dir / "summary.json"
    write_csv(csv_path, deduped, HEADERS)
    write_csv(audit_csv_path, deduped, [*HEADERS, SOURCE_PAGE])
    summary = {
        **dedupe_summary,
        "session_id": session_id,
        "page_range": [state["start_page"], state["end_page"]],
        "page_count": len(state["requested_pages"]),
        "missing_fields": missing_fields,
        "empty_cost": sum(1 for row in deduped if not row.get("造价", "")),
        "empty_investment": sum(1 for row in deduped if not row.get("总投资额", "")),
        "per_page": per_page,
    }
    save_json(summary_path, summary)

    node_exe = resolve_node_executable(args.node_exe)
    node_modules = resolve_node_modules(args.node_modules)
    if not paths.builder.exists():
        raise SystemExit(f"找不到 Excel 构建器：{paths.builder}")
    ensure_node_modules(paths, node_modules)

    output_dir = Path(args.output_dir) if args.output_dir else paths.root / "outputs" / session_id
    output_dir.mkdir(parents=True, exist_ok=True)
    output_name = args.output_name or f"RCC项目清单_第{state['start_page']}-{state['end_page']}页.xlsx"
    output_path = output_dir / output_name
    preview_path = output_dir / f"{output_path.stem}_preview.png"
    inspect_path = output_dir / f"{output_path.stem}_inspect.ndjson"
    result = subprocess.run(
        [str(node_exe), str(paths.builder), str(csv_path), str(output_path), str(preview_path), str(inspect_path), str(len(deduped))],
        cwd=str(paths.code_root), check=True, capture_output=True, text=True, encoding="utf-8",
    )
    state["status"] = "EXPORTED"
    state["last_export"] = {
        "exported_at": utc_now(), "rows": len(deduped), "output_path": str(output_path),
        "preview_path": str(preview_path), "summary_path": str(summary_path), "inspect_path": str(inspect_path),
    }
    persist_state(paths, session_id, state)
    emit({"action": "export", "session_id": session_id, "status": "EXPORTED", "rows": len(deduped), "output_path": str(output_path), "preview_path": str(preview_path), "summary_path": str(summary_path), "builder_output": result.stdout.strip()})


def command_status(args, paths: Paths) -> None:
    session_id, _, state = resolve_session(paths, args.session)
    captured = {item["page"] for item in state.get("captured_pages", [])}
    emit({
        "session_id": session_id,
        "status": state["status"],
        "page_range": [state["start_page"], state["end_page"]],
        "captured_page_count": len(captured),
        "captured_pages": sorted(captured),
        "missing_pages": [page for page in state["requested_pages"] if page not in captured],
        "next_expected_page": state.get("next_expected_page"),
        "settings": state.get("settings"),
        "last_export": state.get("last_export"),
    })


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RCC 网页逐页抓取、断点续跑和 8 列 Excel 导出工作流。")
    parser.add_argument("--workspace-root", default="", help=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor_parser = subparsers.add_parser("doctor", help="检查 Python、Node.js 和 Excel 导出依赖。")
    doctor_parser.add_argument("--node-exe", default="")
    doctor_parser.add_argument("--node-modules", default="")
    doctor_parser.set_defaults(func=command_doctor)

    new_parser = subparsers.add_parser("new", help="创建新的抓取批次。")
    new_parser.add_argument("--start-page", type=int, required=True)
    new_parser.add_argument("--end-page", type=int, required=True)
    new_parser.add_argument("--label", default="rcc")
    new_parser.set_defaults(func=command_new)

    confirm_parser = subparsers.add_parser("confirm", help="记录已确认的网页设置。")
    confirm_parser.add_argument("--session", default="")
    confirm_parser.add_argument("--current-page", type=int, required=True)
    confirm_parser.add_argument("--page-size", type=int, required=True)
    confirm_parser.add_argument("--page-title", default="")
    confirm_parser.add_argument("--source-url", default="")
    confirm_parser.add_argument("--filter-summary", default="")
    confirm_parser.add_argument("--sort-summary", default="")
    confirm_parser.set_defaults(func=command_confirm)

    start_parser = subparsers.add_parser("start", help="用户明确开始后切换为抓取状态。")
    start_parser.add_argument("--session", default="")
    start_parser.set_defaults(func=command_start)

    save_parser = subparsers.add_parser("save-page", help="保存一页原始文本并更新断点。")
    save_parser.add_argument("--session", default="")
    save_parser.add_argument("--page", type=int, required=True)
    save_parser.add_argument("--input", default="")
    save_parser.add_argument("--source-url", default="")
    save_parser.set_defaults(func=command_save_page)

    export_parser = subparsers.add_parser("export", help="解析全部页面并导出 Excel。")
    export_parser.add_argument("--session", default="")
    export_parser.add_argument("--output-dir", default="")
    export_parser.add_argument("--output-name", default="")
    export_parser.add_argument("--allow-incomplete-records", action="store_true")
    export_parser.add_argument("--node-exe", default="")
    export_parser.add_argument("--node-modules", default="")
    export_parser.set_defaults(func=command_export)

    status_parser = subparsers.add_parser("status", help="查看当前阶段、缺失页和下一页。")
    status_parser.add_argument("--session", default="")
    status_parser.set_defaults(func=command_status)
    return parser


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args()
    default_root = Path(__file__).resolve().parents[1]
    paths = Paths(Path(args.workspace_root).resolve() if args.workspace_root else default_root, default_root)
    args.func(args, paths)


if __name__ == "__main__":
    main()

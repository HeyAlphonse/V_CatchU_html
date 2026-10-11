import re
from collections import Counter, defaultdict


HEADERS = ["ID", "项目名称", "省份", "城市", "项目阶段", "造价", "总投资额", "更新时间"]
SOURCE_PAGE = "来源页码"

PROVINCES = [
    "广西壮族自治区", "新疆维吾尔自治区", "西藏自治区", "宁夏回族自治区", "内蒙古",
    "黑龙江省", "北京", "天津", "上海", "重庆", "河北省", "山西省", "辽宁省", "吉林省",
    "江苏省", "浙江省", "安徽省", "福建省", "江西省", "山东省", "河南省", "湖北省",
    "湖南省", "广东省", "海南省", "四川省", "贵州省", "云南省", "陕西省", "甘肃省",
    "青海省", "台湾省", "广西省", "广西", "新疆", "西藏", "宁夏省", "宁夏", "香港", "澳门",
]

ID_RE = re.compile(r"^\d{6,8}$")
PROVINCE_RE = re.compile(
    r"(" + "|".join(re.escape(item) for item in sorted(PROVINCES, key=len, reverse=True)) + r")\s*/\s*(.+)$"
)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}$")
NUMBER_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
SKIP_PREFIXES = (
    "项目有进展:", "项目有进展且参与人有变动:", "项目添加了高管/参与人:",
    "参与人有变动:", "补齐资料:",
)


def is_note(line: str) -> bool:
    if line.startswith(SKIP_PREFIXES):
        return True
    return line.startswith("项目") and any(marker in line for marker in ("截止", "参与人", "进展"))


def parse_text(text: str, source_page: int | str = "") -> list[dict[str, str]]:
    lines = [line.strip() for line in text.replace("\u00a0", " ").splitlines()]
    rows: list[dict[str, str]] = []
    index = 0

    while index < len(lines):
        if not ID_RE.fullmatch(lines[index]):
            index += 1
            continue

        project_id = lines[index]
        index += 1
        name_parts: list[str] = []
        province = ""
        city = ""
        stage = ""
        numbers: list[str] = []
        updated_at = ""
        skipping_note = False

        while index < len(lines):
            line = lines[index]
            if ID_RE.fullmatch(line):
                break
            if not line:
                index += 1
                continue

            province_match = PROVINCE_RE.search(line)
            if province_match:
                before = line[: province_match.start()].strip()
                if before and not skipping_note:
                    name_parts.append(before)
                province = province_match.group(1).strip()
                city = province_match.group(2).strip()
                index += 1
                break

            if is_note(line):
                skipping_note = True
                index += 1
                continue

            if not skipping_note:
                name_parts.append(line)
            index += 1

        while index < len(lines):
            line = lines[index]
            if ID_RE.fullmatch(line):
                break
            if not line:
                index += 1
                continue
            if DATE_RE.fullmatch(line):
                updated_at = line
                index += 1
                break
            if NUMBER_RE.fullmatch(line):
                numbers.append(line)
                index += 1
                continue
            if not stage:
                stage = line
            index += 1

        rows.append({
            "ID": project_id,
            "项目名称": " ".join(part for part in name_parts if part).strip(),
            "省份": province,
            "城市": city,
            "项目阶段": stage,
            "造价": numbers[0] if numbers else "",
            "总投资额": numbers[1] if len(numbers) > 1 else "",
            "更新时间": updated_at,
            SOURCE_PAGE: str(source_page),
        })

    return rows


def project_key(row: dict[str, str]) -> tuple[str, str, str, str]:
    return (row.get("ID", ""), row.get("项目名称", ""), row.get("省份", ""), row.get("城市", ""))


def dedupe_rows(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], dict]:
    seen: set[tuple[str, str, str, str]] = set()
    deduped: list[dict[str, str]] = []
    exact_duplicates = 0
    id_counts = Counter(row.get("ID", "") for row in rows)
    variants: defaultdict[str, set[tuple[str, str, str]]] = defaultdict(set)

    for row in rows:
        variants[row.get("ID", "")].add((row.get("项目名称", ""), row.get("省份", ""), row.get("城市", "")))
        key = project_key(row)
        if key in seen:
            exact_duplicates += 1
            continue
        seen.add(key)
        deduped.append(row)

    return deduped, {
        "raw_rows": len(rows),
        "unique_rows": len(deduped),
        "exact_duplicate_rows": exact_duplicates,
        "duplicate_project_id_count": sum(1 for count in id_counts.values() if count > 1),
        "conflicting_project_id_count": sum(1 for values in variants.values() if len(values) > 1),
    }

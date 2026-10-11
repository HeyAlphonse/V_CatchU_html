# RCC 网页抓取工作流说明

## 三个阶段

### 1. 网页设置确认

用户给出本次起止页，例如第 1–40 页。Codex 创建新批次后，在不刷新页面的前提下检查：

- 页面确实是 RCC 项目列表页；
- 筛选条件和排序符合本次需求；
- 当前页等于起始页；
- 每页条数已经设置好；
- 结果总数/总页数足以覆盖结束页；
- 项目列表文本可读取；
- “下一页”按钮存在且可用。

检查完成后，用户确认设置无误，工作流进入 `READY` 状态。

### 2. 逐页抓取

用户明确说“开始”后，工作流进入 `CAPTURING` 状态。每一页都严格执行：

1. 读取当前页码和项目列表区域文本；
2. 确认文本中存在 RCC 项目 ID；
3. 保存原始文本和页面元数据；
4. 更新状态中的已完成页与下一页；
5. 仅在保存成功后点击“下一页”；
6. 等待页码或首条项目 ID 变化，再继续下一页。

这是断点续跑设计。浏览器或任务中断后，`status` 会返回 `next_expected_page`，从该页继续即可。

遇到以下情况时暂停：限流提示、验证码、登录失效、项目列表为空、页码不符、下一页无效、同一页内容异常变化。

### 3. Excel 导出

指定页全部齐全后，工作流进入 `CAPTURED` 状态。导出时：

- 按页面顺序解析；
- 固定输出 8 列；
- 以 `ID + 项目名称 + 省份 + 城市` 去重；
- 金额以数值保存，更新时间以 Excel 日期时间保存；
- 对关键字段缺失、重复、冲突和每页行数生成 JSON 校验摘要；
- 生成带筛选、冻结表头和合理列宽的 Excel；
- 渲染首屏预览用于视觉检查。

## 状态与文件

每次运行创建独立批次：

```text
.codex_work/rcc_web_capture/sessions/<批次ID>/
  state.json
  raw_pages/page_0001.txt
  page_metadata/page_0001.json
  parsed/projects.csv
  parsed/summary.json

outputs/<批次ID>/
  RCC项目清单_第1-40页.xlsx
  RCC项目清单_第1-40页_preview.png
```

历史批次不会被新批次覆盖，也不会自动并入参考项目已有数据。

## 命令

以下命令由 Codex 在工作流中执行，通常不需要用户手工运行。

```powershell
python scripts/rcc_capture_workflow.py new --start-page 1 --end-page 40 --label 20260824
python scripts/rcc_capture_workflow.py confirm --current-page 1 --page-size 100 --page-title "RCC工程信息网-项目列表页" --filter-summary "用户已确认当前筛选"
python scripts/rcc_capture_workflow.py start
python scripts/rcc_capture_workflow.py save-page --page 1 --input <page_0001.txt> --source-url <url>
python scripts/rcc_capture_workflow.py status
python scripts/rcc_capture_workflow.py export
```

若不是第 1 页开始，例如第 12–20 页，只需在 `new` 时指定对应范围。

# RCC 网页项目抓取与 Excel 导出

这是一个可重复、可指定页码范围、可中断续跑的三阶段工作流。

## 工作方式

1. Codex 先带你检查 RCC 网页的筛选条件、排序、每页条数、当前页码和“下一页”按钮。
2. 你明确说“开始”后，Codex 逐页读取项目列表文本；每页保存成功后才进入下一页。
3. 指定页面全部抓取完成后，工作流解析、去重并导出 8 列 Excel。

固定字段：`ID`、`项目名称`、`省份`、`城市`、`项目阶段`、`造价`、`总投资额`、`更新时间`。


## 新电脑快速开始

适用环境：Windows 10/11、Python 3.10 或更高版本、Git、Codex 桌面版。Python 抓取工作流只使用标准库，无需 `pip install`。Excel 导出使用 Codex 桌面版内置的工作区依赖。

```powershell
git clone https://github.com/HeyAlphonse/V_CatchU_html.git
cd V_CatchU_html
python scripts/rcc_capture_workflow.py doctor
python -m unittest discover -s tests
```

`doctor` 返回 `"status": "OK"` 后，在 Codex 中打开该目录，登录 RCC 网页，即可按 `AGENTS.md` 中的工作流使用。不同电脑的用户名可以不同，脚本会自动发现当前用户的 Codex 运行环境。

## 本地数据与续跑

`.codex_work/`保存原始页文本、批次状态和断点，`outputs/`保存导出结果。两者可能包含业务数据，默认不提交到 Git。

- 只需在新电脑开始新批次：直接克隆仓库。
- 需在新电脑续跑原批次：通过受信任的私有存储额外复制 `.codex_work/rcc_web_capture/`。

不要向 Git 提交 RCC 账号、Cookie、Token、浏览器配置或 `.env` 密钥。

## 依赖路径覆盖

如果 Codex 运行时位于非标准位置，可使用 `RCC_NODE_EXE` 和 `RCC_NODE_MODULES` 环境变量，或在 `doctor` / `export` 命令中传入 `--node-exe` 和 `--node-modules`。

详细说明见 [docs/rcc_web_capture_workflow.md](docs/rcc_web_capture_workflow.md)。

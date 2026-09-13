# 環境安裝與使用手冊（交接用 Runbook）

給接手這個專案的人看的完整步驟：從零建立能執行「讀 release note → 改 config → 驗證 → 開 PR」workflow 的環境，並知道日常怎麼用。不需要回頭翻對話紀錄。

---

## 0. 前置需求

- Node.js（建議 v20+）與 npm
- Python 3.10+
- （**optional，僅供個人在家測試用**）Ollama
- 公司內部 LLM API 的存取資訊：base URL、API key、model 名稱（向負責 LLM 平台的窗口索取）

---

## 1. 建立獨立的 Python 環境（跑 `validate_config.py` 用）

用 conda（或熟悉的 venv 亦可）：

```bash
conda create -n qwen-ai-ops python=3.11 -y
conda activate qwen-ai-ops
pip install pyyaml charset-normalizer
```

之後每次要手動跑驗證腳本，記得先 `conda activate qwen-ai-ops`。

---

## 2. 在專案內本地安裝 qwen-code（不要用 `-g` 全域安裝）

在專案根目錄：

```bash
npm init -y                      # 如果還沒有 package.json
npm install @qwen-code/qwen-code
npx qwen --version                # 確認安裝成功
```

用本地安裝、`npx qwen` 呼叫，不會動到這台機器上其他專案或其他使用者的全域 npm 狀態。

---

## 3. 設定 LLM 後端

### 方案 A（正式使用）：接公司 LLM API

在專案根目錄建立 `.env`（**不要 commit**，已加進 `.gitignore`）：

```bash
OPENAI_API_KEY=<公司 API key>
OPENAI_BASE_URL=<公司 LLM API 的 base URL，需相容 OpenAI /v1/chat/completions 格式>
OPENAI_MODEL=<公司提供的 model 名稱>
```

> 如果公司 API **不是** OpenAI 相容格式（例如走 Anthropic 協定、或自家的認證方式），不能只改這三個環境變數，需要在 `.qwen/settings.json` 用 `modelProviders` 明確宣告 provider/protocol。細節見 qwen-code 內建文件 `node_modules/@qwen-code/qwen-code/bundled/qc-helper/docs/configuration/model-providers.md`。

### 方案 B（optional，個人在家測試用）：本機 Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5-coder:latest      # 或其他要測試的模型
ollama serve                           # 多半會裝成 systemd service 自動啟動，不用每次手動下
```

`.env` 改成：

```bash
OPENAI_API_KEY=ollama
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_MODEL=qwen2.5-coder:latest
```

**⚠️ 已知限制（2026-09-13 實測）**：目前 qwen-code 0.23.3 的 headless（`-p`）agent 架構，要求驅動它的模型要能穩定處理「目標追蹤協議」（`get_goal`/`update_goal`，含 `evidenceRefs`/`blockerKind` 等欄位）以及「延遲工具搜尋」（`tool_search`）。實測 `qwen2.5-coder:latest`（7.6B）與 `qwen3:32b` 兩個本地模型都**無法穩定驅動**這個流程（細節見第 5 節）。**如果改用公司提供、能力更強的雲端模型，這個問題不一定會發生，但正式導入前務必照第 4 節『驗證清單』實測過一次，不要假設裝完就能動。**

---

## 4. 專案內既有的設定檔（已建立好，不需重做）

| 檔案 | 用途 |
|---|---|
| `QWEN.md` | qwen-code 啟動時自動讀取的任務規則（agent 系統層級指示：能做/不能做什麼、驗證指令怎麼下） |
| `.qwen/settings.json` | 專案層級設定，目前關閉 `tool_search`（`{"tools":{"toolSearch":{"enabled":false}}}`），讓內建工具（讀檔/寫檔/跑 shell）一開始就直接可見，不用模型自己先搜尋才找得到 |
| `.gitignore` | 排除 `node_modules/`、`.env`，避免密鑰或相依套件被 commit |
| `agent_skill/SKILL.md` | 給人看的完整 workflow 規則說明（含錯誤代碼對照表），內容與 `QWEN.md` 一致 |

---

## 5. 驗證清單（拿到新環境後，一定要照順序跑一次，不要跳過）

**第一步：確認驗證腳本本身能跑**（跟 agent/LLM 完全無關，先排除腳本本身壞掉的可能）：

```bash
conda activate qwen-ai-ops
cd validator
python3 validate_config.py --schemas-dir schemas --list-services
# 預期輸出: service-fab-a / service-fab-b
```

**第二步：確認 LLM 後端本身能回應**（先不牽扯 agent 工具呼叫）：

```bash
cd ..
set -a && source .env && set +a
npx qwen -p "reply with exactly the word: PONG"
# 預期輸出: PONG
```

**第三步：確認 agent 真的能驅動 shell 工具去跑驗證腳本**（這一步才代表整套 workflow 能不能動）：

```bash
npx qwen --approval-mode auto -p "Run the command to list available services from the config validator, per QWEN.md, and just tell me the list."
```

如果這步驟失敗（模型亂編工具名稱、回報格式錯誤的 JSON、或直接說「做不到」），代表目前這個 LLM 後端還無法穩定驅動 qwen-code，需要換模型或換 CLI，**不要**直接拿去跑正式任務。

---

## 6. 已知問題記錄（本機 Ollama 模型實測結果，供除錯參考，不代表公司 API 也會遇到）

- `qwen2.5-coder:latest`（7.6B）：在目標追蹤回報裡直接把範例佔位文字 `<uuid-from-evidenceCatalog>` 原封不動貼進真正的輸出，代表沒有產生有效值；也曾在完全沒有嘗試執行的情況下，直接判定任務「做不到」
- `qwen3:32b`：重複呼叫一個打錯名字的 shell 工具（`run_shell` / `run_command`），即使提示詞中已經明講正確名稱是 `run_shell_command`，仍然打錯
- `validator/schemas/custom-device-config.schema .yaml` 檔名裡有一個多餘的空白（正確應為 `custom-device-config.schema.yaml`），導致這個 schema 目前無法被 `--service`/`--list-services` 的命名慣例自動找到，只能用 `--schema` 直接指定路徑呼叫。尚未修正，交接者可自行評估是否要處理。

---

## 7. 日常使用方式

### 7.1 直接手動跑驗證腳本（不透過 agent，人工改完 config 後自己把關）

```bash
conda activate qwen-ai-ops
python3 validator/validate_config.py \
  --schemas-dir validator/schemas --service {service} \
  --config {config_path} --context factory={factory}
```

- 需要結構化輸出給程式解析，加 `--json`
- 想知道目前有哪些 service 可選：加 `--list-services`
- 詳細參數與六種 typo 情境說明見 `validator/README.md`、`docs/02-typo-detection-spec.md`

### 7.2 透過 qwen agent 執行「讀 release note → 改 config → 驗證 → 開 PR」任務

```bash
set -a && source .env && set +a
npx qwen --approval-mode auto "請根據 release-note.md 的說明，修改 configs/{service}/prod.yaml，
廠別是 {factory}，改完後幫我驗證並開一個 PR"
```

- 執行前務必先過完第 5 節的『驗證清單』三步驟
- agent 的行為邊界（可以做/不可以做什麼）定義在 `QWEN.md`（給 qwen-code 讀）與 `agent_skill/SKILL.md`（給人看的完整版說明，含錯誤代碼對照表），兩份內容一致
- agent 停下來詢問情境參數（例如廠別 A/B）是**設計上刻意的行為**，不是 bug——這個值必須由任務發起人明確提供，不可以讓 agent 自己猜

### 7.3 新增/修改 schema（只有開發/資深維運能做，agent 不行）

- 位置：`validator/schemas/{service}.schema.yaml`
- PR 前務必跑 `python3 validate_config.py --schema schemas/{service}.schema.yaml --lint-schema`
- 細節見 `docs/01-workflow-design.md` 第 4 節

---

## 8. 檔案總覽

| 檔案 | 用途 |
|---|---|
| `QWEN.md` | qwen-code 讀取的任務規則（agent 系統層級指示） |
| `.env` | LLM 後端連線設定（不 commit） |
| `.qwen/settings.json` | qwen-code 專案層級設定（目前關閉 `tool_search`） |
| `agent_skill/SKILL.md` | 給人看的完整 workflow 規則說明 |
| `validator/validate_config.py` | 驗證腳本本體 |
| `validator/schemas/*.schema.yaml` | 各 service 的合法欄位規則 |
| `docs/01~04` | 設計文件（workflow、typo 偵測規格、prompt 範本、CLI 實作指南） |
| `docs/05-environment-setup-and-usage.md` | 本文件 |

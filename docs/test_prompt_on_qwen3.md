# 實測記錄：qwen-code + 本地 Ollama 模型的 prompt 與結論

這份文件記錄實際下給 `qwen-code`（透過 Ollama 跑本地模型）的每一句 prompt、確切指令、以及觀察到的結果與結論。目的是讓後面接手的人不用重跑一次就能知道「哪些做法有效、哪些沒效、為什麼」。

所有測試共同前提：
```bash
export OPENAI_API_KEY=ollama
export OPENAI_BASE_URL=http://localhost:11434/v1
export OPENAI_MODEL=<測試模型>
npx qwen [flags] -p "<prompt>"
```
除非特別註明，都在專案根目錄（`/home/willy8898/Project/Qwen_ai_ops`）執行，並用 `-d`（`--debug`）檢查 debug log 裡實際發生的 tool call。

---

## Phase 0：基礎連線測試（確認 Ollama/模型本身沒問題）

**Prompt：**
```
reply with exactly the word: PONG
```
**模型：** `qwen2.5-coder:latest`、`qwen3:8b`（皆測過）
**結果：** 兩者都正確回 `PONG`。
**結論：** Ollama 服務、模型本身、qwen-code CLI 的基本問答迴路都正常。後面所有失敗都跟「工具呼叫」這件事有關，不是連線或模型本身壞掉。

---

## Phase 1：直接叫模型組 `validate_config.py` 的完整多 flag 指令

這個階段還沒關閉 `tool_search`，也還沒做任何窄接口包裝，單純測試「模型能不能自己組出正確的 shell 指令」。

### 1.1
**Prompt：**
```
Run the command to list available services from the config validator, per QWEN.md, and just tell me the list.
```
**模型／參數：** `qwen2.5-coder:latest`，`--approval-mode auto`
**結果：** 模型呼叫 `update_goal` 想回報 `report_error`，但 `report_error` 根本不是註冊過的工具名稱，整個 goal 被標記為 `blocked`。
**結論：** 模型連「目標追蹤協議」要用的工具名稱都會編錯，還沒進到 shell 呼叫這一步就卡住。

### 1.2
**Prompt：** 同上
**模型／參數：** `qwen3:32b`，`--approval-mode auto`
**結果：** 模型直接回一串完全不存在的工具清單（`artifact_download`、`file_upload`、`image_capturer` 等），從頭到尾沒有真的呼叫任何工具。
**結論：** `tool_search` 機制下，模型連「該搜尋什麼關鍵字才找得到 shell 工具」都猜不對。

### 1.3
**Prompt：**
```
First use tool_search to find the shell/command execution tool (try query 'shell'). Then use it to run: python3 validator/validate_config.py --schemas-dir validator/schemas --list-services . Tell me the exact output.
```
**模型／參數：** `qwen3:32b`，`--approval-mode yolo`
**結果：** 又編出另一批不存在的工具名稱，同樣沒有真正執行。
**結論：** 就算明講「先用 tool_search 搜尋 shell」，模型還是不會照做。

> 之後在 `.qwen/settings.json` 加上 `{"tools":{"toolSearch":{"enabled":false}}}`，讓內建工具（含 `run_shell_command`）從一開始就直接可見，不用模型自己搜尋。

### 1.4
**Prompt：**
```
Run: python3 validator/validate_config.py --schemas-dir validator/schemas --list-services . Tell me the exact output.
```
**模型／參數：** `qwen3:32b`，`--approval-mode yolo -d`
**結果：** debug log 顯示模型呼叫了 `run_shell`（不存在，正確名稱是 `run_shell_command`），連續兩次都打錯同一個錯名稱。
**結論：** 關掉 `tool_search` 後工具確實可見了，但模型自己編了一個聽起來合理、實際上錯誤的工具名稱。

### 1.5
**Prompt：**
```
Use the run_shell_command tool (that is its exact, correct name) to run: python3 validator/validate_config.py --schemas-dir validator/schemas --list-services . Tell me the exact output.
```
**模型／參數：** `qwen3:32b`，`--approval-mode yolo`
**結果：** 即使明講正確名稱，模型還是呼叫了 `run_command`（依然錯），拿到錯誤訊息後沒有重試，直接反問使用者要不要用 `run_shell_command`。
**結論：** 光靠 prompt 裡講清楚正確名稱，無法根治這個問題；模型有很強的慣性想打 `run_command` 這個（不存在的）名字。

### 1.6
**Prompt：**
```
Use the run_shell_command tool to run: python3 validator/validate_config.py --schemas-dir validator/schemas --list-services . Tell me the exact output.
```
**模型／參數：** `qwen2.5-coder:latest`，`--approval-mode yolo`
**結果：** 模型輸出一段格式錯誤的 `update_goal` JSON，`evidenceRefs` 欄位裡直接塞了字面上的 placeholder 文字 `<uuid-from-evidenceCatalog>`（沒有產生真正的值），並判定任務「做不到」。
**結論：** 這顆模型在目標追蹤協議上的問題比工具命名問題更嚴重——它會編出格式錯誤的 JSON，還沒試就放棄。

### 1.7（換模型：`qwen3:8b`）
**Prompt：**
```
Run the command to list available services from the config validator, per QWEN.md, and just tell me the list.
```
**模型／參數：** `qwen3:8b`，`--approval-mode auto -d`
**結果：** 模型呼叫了 `skill` 工具、傳入不存在的 skill 名稱 `"config-validator"`，被拒絕後列出真正存在的 skill 清單（`batch`、`dataviz`...），但沒有再嘗試呼叫 shell 工具。
**額外發現：** debug log 顯示 `--approval-mode auto`（沒有 `--sandbox`）時，`ToolRegistry` 裡**根本沒有** `run_shell_command`／`write_file`／`edit`／`notebook_edit`／`monitor` 這幾個工具（21 個 vs `yolo` 模式下的 26 個）。也就是說在 `auto` 模式、沒設定 sandbox 的情況下，這幾個工具從一開始就沒被註冊，不是模型不會用，是它真的拿不到。
**結論：** 之後測試一律改用 `--approval-mode yolo`，確保工具真的有註冊。

### 1.8
**Prompt：** 同 1.4（"Run: python3 validator/validate_config.py ..."）
**模型／參數：** `qwen3:8b`，`--approval-mode yolo -d`
**結果：** 跟 1.4 的 `qwen3:32b` 一樣，呼叫了不存在的 `run_command`。
**結論：** 這個「打錯 shell 工具名稱」的問題不分模型大小，`qwen3:32b`、`qwen3:8b` 都一樣會犯。

### 1.9（決定性的一次失敗）
**Prompt：**
```
There is no tool called run_command. The only shell execution tool is named exactly run_shell_command. Call run_shell_command now with command=python3 and args=[validator/validate_config.py, --schemas-dir, validator/schemas, --list-services]. Then tell me the exact stdout.
```
**模型／參數：** `qwen3:8b`，`--approval-mode yolo -d`（後續用 180 秒逾時再測一次，並直接用 `ps --forest` 檢查即時 process tree）
**結果：** 這次模型真的呼叫了名稱正確的 `run_shell_command`（debug log 顯示 `settled` 沒有 ERROR），但把參數拆成 `command="python3"` + 獨立的 `args=[...]` 陣列（很像它訓練資料裡熟悉的 `subprocess.run()` 呼叫簽名）。工具實際執行時因為只吃單一指令字串，最後只跑了裸的 `python3`，掉進互動式 REPL 卡住等 stdin。用 `ps --forest` 直接抓到殘留的 `python3` 行程，狀態 `Ss+`（session leader、在 pty 上等輸入），確認就是卡在 REPL，直到工具內建的 120 秒逾時才被砍掉。
**結論：** 這是本次調查最關鍵的一次失敗——證明「工具名稱猜對了」不代表「參數格式也會對」。模型會把單一指令字串拆成 `command`+`args` 這種它更熟悉的呼叫慣例，但這個工具的 schema 不吃這種格式。這直接指向了後面「窄接口」設計的必要性：與其讓模型自己決定怎麼組指令/參數形狀，不如乾脆只給它填 2～3 個純位置參數的空間。

---

## Phase 2：改用 MCP 工具化（結論：此路不通，但值得記錄原因）

先寫了 `optional-advanced-mcp/server.py`，把驗證邏輯包成 `list_services()` / `validate_config(service, config_path, context)` 兩個 MCP tool，塞進 `.qwen/settings.json` 的 `mcpServers`。用獨立的 Python MCP client 直接測試（不透過 LLM）確認 server 本身沒問題（正確處理未知 service、路徑跳脫、真實驗證錯誤等），但接上 `qwen-code` 之後：

### 2.1
**Prompt：**
```
List the available services, per QWEN.md.
```
**模型／參數：** `qwen3:8b`，`--approval-mode auto -d`
**結果：** 模型呼叫 `web_fetch`，對象是幻想出來的網址 `https://example.com/QWEN.md`，回傳 404。
**結論：** 這句 prompt 本身用詞含糊（「per QWEN.md」被模型誤解成一個要去抓的網址），純粹是我下的 prompt 不夠精確，跟 MCP 本身無關。

### 2.2
**Prompt：**
```
Call the list_services tool from the config-validator MCP server now and tell me what it returns.
```
**模型／參數：** `qwen3:8b`，`--approval-mode yolo -d`（MCP server 尚未 approve）
**結果：** 模型呼叫 `web_fetch`，對象是幻想出來的 `https://config-validator-server/api/list_services`，DNS 解析失敗。
**結論：** 這時發現 `qwen mcp list` 顯示這個 server 狀態是 **Pending approval**——workspace 提供的 MCP server 需要明確核准才會真的連線。

跑了 `qwen mcp approve config-validator`，狀態變成 `Connected`，重測同一句 prompt：

### 2.3
**Prompt：** 同 2.2
**模型／參數：** `qwen3:8b`，`--approval-mode yolo -d`（已 approve）
**結果：** 模型還是編出一堆不存在的工具名稱（`run_script`、`send_email`、`list_tools`...），debug log 的 `ToolRegistry created` 清單裡完全沒有 `list_services`／`validate_config`。
**結論：** 核准了也沒用——工具根本沒被載入這次的 session。

在 server 設定加上 `"trust": true`（config 內容一變又打回 `Pending approval`，重新 approve）後再測一次，結果一樣：`ToolRegistry` 裡還是沒有 MCP 工具。

**最終確認（非 prompt，屬於原始碼層級檢查）：** 翻遍 `node_modules/@qwen-code/qwen-code/chunks/nonInteractiveCli-LSJSQ2W4.js` 實際 import 的整包依賴（`chunk-NMCDMLHL.js`，2190 行），完全沒有任何 `mcp` 字樣；`qwen mcp list`/`qwen mcp approve` 顯示的連線狀態是另一條、獨立的探測路徑，跟 `qwen -p ...` 這次真正執行時會不會接上 MCP 完全是兩回事。

**結論：目前這個版本（0.23.3）的 qwen-code，headless（`-p`）模式完全沒有接上 MCP，不管怎麼設定 approve/trust 都一樣。** MCP server 程式碼保留，但標記為「目前這個 headless 用法用不到」。

---

## Phase 3：改用「參數極簡的 CLI 包裝腳本」（結論：這個方向有效）

寫了 `validator/run_validation.py`（只吃 `<service> <config_path> [key=value ...]` 純位置參數，沒有 flag），並在 `QWEN.md` 明講「只能呼叫這支腳本，不可以自己組 `validate_config.py` 的完整指令」。

### 3.1（過渡期，prompt 用詞仍含糊）
**Prompt：**
```
Per QWEN.md, validate the service-fab-a schema against validator/schemas/service-fab-a.schema.yaml itself is not a config, so instead just call the validation wrapper with no arguments to see the usage message and list of known services. Report exactly what it prints.
```
**模型／參數：** `qwen3:8b`，`--approval-mode yolo -d`
**結果：** 又去 `web_fetch` 一個幻想網址，404。
**結論：** 跟 2.1 一樣，是我這句 prompt 寫得太繞，不是包裝腳本的問題。

### 3.2
**Prompt：**
```
Use your shell command execution tool to run this exact local command: python3 validator/run_validation.py -- then report exactly what it printed to stdout.
```
**模型／參數：** `qwen3:8b`，`--approval-mode yolo -d`
**結果：** 又打錯成 `run_command`，看到錯誤訊息裡列出正確名稱 `run_shell_command` 後，沒有重試，直接反問使用者。
**結論：** 「工具命名」這個問題本身不受包裝腳本影響（本來就預期如此，因為問題出在挑選工具名稱這一步，不是填參數這一步）。

### 3.3（第一次成功）
**Prompt：**
```
Call the tool named run_shell_command. Its first parameter should be the string 'python3 validator/run_validation.py'. Report exactly what it printed to stdout.
```
**模型／參數：** `qwen3:8b`，`--approval-mode yolo -d`
**結果：** debug log 顯示模型**連續兩次正確**呼叫 `run_shell_command`，指令字串完全正確（`python3 validator/run_validation.py`），拿回包裝腳本設計中預期的 `USAGE_ERROR`（因為沒帶任何參數，這正是要測的情境）。之後模型另外多此一舉嘗試呼叫一個不存在的 `send_notification` 工具（可能想「通知」使用者），最終文字回覆內容本身是合理的。
**結論：** 驗證呼叫本身**完全正確**；多餘的失敗發生在「怎麼把結果回報給使用者」這個下游步驟，跟驗證工具的介面設計無關。

### 3.4（乾淨的成功案例）
**Prompt：**
```
Call run_shell_command with command 'python3 validator/run_validation.py'. Then, in your final text answer to me (do not use any other tool), quote exactly what it printed.
```
**模型／參數：** `qwen3:8b`，`--approval-mode yolo -d`
**結果：** 正確呼叫 `run_shell_command`，正確解析回傳的 JSON（`USAGE_ERROR`、`suggestion` 欄位列出的合法 service 清單），並在最終文字回覆中正確反問使用者要驗證哪個 service／config（完全符合專案設計原則「情境不足要主動問，不能自己猜」）。
**結論：** 明講「最終答案不要再用其他工具」之後，模型不會再跑去呼叫奇怪的通知類工具。這是第一次完整乾淨成功。

### 3.5（帶真實參數的完整流程）
**Prompt：**
```
Call run_shell_command with command 'python3 validator/run_validation.py service-fab-a validator/examples/_smoketest2.yaml factory=A'. Then, in your final text answer to me (do not use any other tool), tell me whether it passed and if not, quote the exact suggestion field for each error.
```
（`_smoketest2.yaml` 是臨時測試檔案，`mode` 欄位故意打成 `acive`，測完即刪除）
**模型／參數：** `qwen3:8b`，`--approval-mode yolo -d`
**結果：** 正確呼叫、正確帶入 `factory=A`，正確從回傳 JSON 找出 `ENUM_INVALID` 錯誤，精準引用 `suggestion` 欄位內容（`'acive'` → `'active'`），並主動提議要不要幫忙修正檔案。
**結論：** 從「呼叫驗證工具」到「解讀結構化錯誤」這一整條路徑，`qwen3:8b` 配合窄接口設計是可靠的。

### 3.6（同一句 prompt 換回 `qwen2.5-coder:latest`）
**Prompt：** 同 3.4
**模型／參數：** `qwen2.5-coder:latest`，`--approval-mode yolo -d`
**結果：** `run_shell_command` 呼叫本身**正確**（工具名稱對、指令字串對，正確拿到 `USAGE_ERROR`）。但接下來模型自己觸發了目標追蹤協議，連續 6 次呼叫 `update_goal`，每次都少填 `evidenceRefs`（schema 要求至少 1 個元素），最後系統回報「沒有進行中的目標」，模型印出一段沒有意義的 `{}`。
**結論：** 這顆模型在「呼叫驗證工具」這一步跟 `qwen3:8b` 一樣可靠了，問題完全轉移到另一個獨立的機制（目標追蹤協議）上——窄接口解決不了這一塊，因為問題根本不是指令怎麼組。

---

## 總結論

1. **模型會不會打錯 shell 工具名稱、參數格式對不對**：把 `validate_config.py` 的多 flag 完整指令，換成 `run_validation.py <service> <config_path> [key=value ...]` 這種純位置參數的包裝腳本之後，`qwen3:8b` 與 `qwen2.5-coder:latest` **都能穩定正確呼叫**，且能正確解析回傳的結構化 JSON。這證實了「給 agent 一個參數受限的窄接口，取代讓它自己組 CLI 指令」這個做法確實有效，是本次測試最重要的正面結論。
2. **MCP 在目前這個 qwen-code 版本的 headless 模式完全用不上**，不管怎麼 approve/trust 都一樣，是這個 CLI build 本身的限制，程式碼保留但不能依賴它。
3. **窄接口解決不了目標追蹤協議（`get_goal`/`update_goal`）本身的不穩定**：`qwen2.5-coder:latest` 在驗證呼叫成功之後，還是會在這個不相干的機制上卡住重試失敗；`qwen3:8b` 在目前測過的單步任務裡沒有踩到這個問題，但還沒驗證過完整的多步驟任務（讀 release note → 改 config → 驗證 → 重試 → 開 PR）會不會踩到。
4. 下一步如果要驗證完整流程是否可行，應該用 `qwen3:8b` + 目前的 `run_validation.py` 包裝腳本，跑一次真正端到端的「改 config → 呼叫驗證 → 依 suggestion 修正 → 重跑 → 開 PR」任務，觀察目標追蹤協議會不會在更長的多步驟互動中被觸發。

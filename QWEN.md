# Config 修改任務規則

## 專案結構
- 各 service 的規則定義在 `validator/schemas/{service}.schema.yaml`
- 驗證腳本本體是 `validator/validate_config.py`，但**你不可以自己組 shell 指令去跑它**（見下方「驗證工具」）

## 角色邊界（務必遵守）
- 只能修改 config 檔案本身，**不可修改 `validator/schemas/*.schema.yaml`**。release note 提到 schema 裡沒有的欄位，停下來回報，交由開發人員決定是否新增，不可以自己猜一個規則套用
- 不可修改任何非 config 的程式碼檔案
- 情境參數（例如 `factory` 廠別）必須由任務發起人明確提供，不可以自行猜測或套用預設值；任務描述沒提供就停下來詢問
- 重試 3 次仍無法通過驗證，不可以硬開 PR，必須停下來回報卡住的具體錯誤內容

## 驗證工具：只能透過這支包裝腳本呼叫，不可以自己組其他 shell 指令

**規則：修改完 config 之後，一律用你的 shell 工具執行下面這一條指令，不可以直接呼叫 `validator/validate_config.py`，也不可以自己額外加其他 flag：**

```bash
python3 validator/run_validation.py <service> <config_path> [key=value ...]
```

只有這三種東西可以出現在這條指令裡：
1. `service`：exact service id（例如 `service-fab-a`）。不確定的話，直接跑 `python3 validator/run_validation.py`（不加任何參數）：它會回報用法錯誤，但錯誤訊息裡的 `suggestion` 欄位會附上目前所有合法 service 清單，不要憑記憶猜
2. `config_path`：檔案路徑，相對於專案根目錄（例如 `configs/service-a/prod.yaml`）
3. 選填的 `key=value`（例如 `factory=A`）：**只能填任務發起人明確給的值，不可以自己發明或套預設值**；這個 service 如果沒有 context 需求就整個省略，不要自己加

**為什麼限制成這樣**：`validate_config.py` 本尊的完整指令列有很多 flag（`--schemas-dir`、`--service`、`--config`、`--context key=value`、`--json`），實測發現直接組這條指令很容易出錯（打錯 flag 名稱、參數塞錯位置、甚至指令沒帶完整導致卡住不會結束）。這支 `run_validation.py` 包裝腳本把整條指令壓縮成 2～3 個純位置參數，沒有 flag 可以打錯。

指令執行後，stdout 會印出一個 JSON 物件：
```json
{"passed": true_or_false, "results": [{"file": "...", "passed": ..., "errors": [{"path": ..., "code": ..., "message": ..., "current_value": ..., "suggestion": ...}]}]}
```
（或是參數本身就有問題時，直接是 `{"passed": false, "errors": [...]}`，例如 `UNKNOWN_SERVICE`、`INVALID_CONFIG_PATH`、`USAGE_ERROR`）

- exit code `0` 且 `passed: true` 代表全部通過，可以進入開 PR 步驟
- exit code `1` 就照每一項 `suggestion` 修正後，重新執行同一條指令
- 最多重試 3 次；3 次後仍未通過，停下來回報具體卡住的錯誤內容，不要為了通過驗證硬塞一個格式合法但語意可疑的值

（這個專案另外也準備了一個 MCP server 版本的同一套邏輯 `optional-advanced-mcp/server.py`，但目前這個版本的 qwen-code 在 headless/`-p` 模式下不會真的連上 MCP server，所以先不要依賴它，一律用上面的 shell 指令方式。）

## 修改 config 前
1. 先用讀檔工具讀出 `validator/schemas/{service}.schema.yaml`，了解有哪些合法欄位、enum、格式，不要憑經驗猜測
2. 如果 schema 裡有 `context_params`（例如 factory 廠別），這個值必須由任務發起人在任務描述中明確提供；如果沒有提供，停下來詢問，不可以自己猜一個值套用

## 開 PR 前
把最後一次驗證通過的完整輸出，貼進 PR 說明的「驗證結果」區塊，並依照 `agent_skill/SKILL.md` 的 PR 說明模板整理內容。
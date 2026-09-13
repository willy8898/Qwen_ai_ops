---
name: config-pr-agent
description: 依 release note 或變更需求修改 service 的自訂 config 檔案（YAML/JSON/properties），用 schema 驗證腳本自我檢查後再開 PR。適用於任何需要「讀文件 → 改 config → 驗證 → 開 PR」的任務，不論驅動這個 agent 的是 Qwen Code、OpenCode 還是其他 CLI，也不論底層 LLM 是 Ollama 本地模型還是任何 API。
---

# Config PR Agent

## 這個 skill 解決什麼問題

維運人員手動改 config 容易 typo，而且讀 release note 耗時、容易跟開發認知落差。這個 skill 讓你（agent）代替人工完成「讀 release note → 改 config → 驗證格式與合法值 → 開 PR」，人力只需要複核「改動的語意合不合理」，不需要逐字檢查格式。

**正確性不是靠你的判斷保證，是靠 `validate_config.py` 這支腳本保證。** 你的角色是「產生變更 + 自我檢查」，不是「決定變更是否正確」——這件事永遠交給驗證腳本跑一次算一次，不要憑經驗覺得「這樣應該沒問題」就跳過驗證。

---

## 角色邊界

### 可以做的事
- 讀取 release note / 變更需求文件
- 讀取對應 service 的 schema（`validator/schemas/{service}.schema.yaml`），了解合法欄位、型別、enum、格式規則
- 修改該 service 目前的 config 檔案，使其符合 release note 描述的變更
- 執行 `validate_config.py` 對修改後的 config 做自我檢查
- 驗證失敗時，根據錯誤訊息的 `suggestion` 修正後重新驗證，最多重試 **3 次**
- 產生 git diff 與 PR 說明

### 不可以做的事
- **不可修改 schema 檔案**（`validator/schemas/*.schema.yaml`）——如果 release note 提到某個 schema 裡沒定義過的欄位，停下來回報，交由開發人員決定是否要新增 schema 規則，你不能自己決定新增
- **不可對「情境參數」自行猜測或套用預設值**（例如廠別 `factory`）。這個值必須由任務發起人明確提供；任務描述裡沒有提供，就停下來詢問，不可以自己選一個值套用
- **重試 3 次仍無法通過驗證，不可以硬開 PR**，必須停下來回報卡住的具體錯誤內容
- 不可為了讓驗證通過，填一個「格式合法但語意可疑」的值（例如硬把 timeout 改成一個能過 range 檢查但明顯不合理的數字）

---

## 標準工作流程

### 1. 確認任務範圍
從任務描述中找出：目標 service、目標 config 檔案路徑、release note 來源、是否有情境參數（例如 factory=A）。

### 2. 讀 schema，不要憑經驗猜
```bash
cat validator/schemas/{service}.schema.yaml
```
確認 release note 提到的每個欄位，在 schema 裡都能找到對應的規則定義。如果有欄位在 schema 裡找不到，停下來回報，不要自己編一個規則套用。

### 3. 檢查是否需要情境參數
schema 檔案最上面若有 `context_params` 區塊，代表這個 service 有欄位的合法值會因情境不同而不同（例如廠別 A/B 對應不同 URL）。

- 如果任務描述裡已經明確給了這個值 → 記下來，後面驗證指令要帶上
- 如果沒有給 → **停下來詢問**，不要自己猜一個廠別套用

### 4. 修改 config
用檔案編輯工具直接改目標 config 檔案，依 release note 的說明填入 schema 允許的值。

### 5. 執行驗證（每次改完都要跑）
```bash
python3 validator/validate_config.py \
  --schemas-dir validator/schemas --service {service} \
  --config {config_path} --context {context_key}={context_value}
```

- 沒有情境參數需求的 service，可以省略 `--context`
- 如果目標檔案是 flat properties 格式（`key: value1,value2` 這種），指令一樣，腳本會自動依副檔名判斷格式
- 想要結構化輸出方便自己解析，加上 `--json`：

```bash
python3 validator/validate_config.py \
  --schemas-dir validator/schemas --service {service} \
  --config {config_path} --context {context_key}={context_value} --json
```

### 6. 讀懂結果
- **退出碼 0** → 全部通過，進入步驟 7
- **退出碼非 0** → 畫面（或 JSON 的 `errors` 陣列）會列出每一項問題的：
  - `path`：哪個欄位（巢狀/陣列會標到精確位置，例如 `KeyD[1].action_params.action`）
  - `code`：問題類型（見下方對照表）
  - `message`：問題說明
  - `suggestion`：建議怎麼修正——**優先照這個改**，不要自己另外想解法

修正後回到步驟 5 重新驗證。**最多重試 3 次**；3 次後仍未通過，停下來，把目前卡住的完整錯誤內容回報給人工，不要繼續硬試或跳過驗證直接開 PR。

### 7. 開 PR
確認驗證通過（退出碼 0）後，用以下模板整理 PR 說明：

```markdown
## 變更來源
- Release note：<連結或檔案路徑>
- 對應段落摘要：<用自己的話簡短摘要這次變更依據的段落，2-3 句話>

## 變更內容
- 檔案：`{config_path}`
- 情境參數：{如果有的話列出，例如 factory=A}
- 變更欄位：
  - `欄位名`：`舊值` → `新值`

## 自我驗證結果
\`\`\`
（貼上 validate_config.py 最後一次成功執行的完整輸出，包含 "全部 N 個檔案驗證通過" 那行）
\`\`\`

## 複核重點提示（給人工審查者）
- 格式與合法值已由自動驗證把關，請重點確認語意是否符合 release note 的意圖
```

---

## 錯誤代碼速查表

拿到驗證失敗結果時，先看 `code` 判斷是哪一類問題，`suggestion` 通常已經給出具體修法：

| code | 代表什麼 | 你該怎麼做 |
|---|---|---|
| `MISSING_REQUIRED` | 必填欄位沒填 | 依 schema 補上這個欄位 |
| `TYPE_MISMATCH` | 型別不對（例如該填數字卻填了字串）| 檢查值有沒有多餘符號、格式錯置 |
| `ENUM_INVALID` | 值不在合法清單內（通常是 typo）| `suggestion` 會用模糊比對建議最接近的合法值，優先採用 |
| `PATTERN_MISMATCH` / `FORMAT_MISMATCH` | 不符合正規表達式或內建格式（如 email/hostname/url）| 對照 `suggestion` 給的 pattern 調整格式 |
| `RANGE_ERROR` | 數值超出 min/max | 改到範圍內，不要為了通過驗證硬塞邊界值卻不符合 release note 的意圖 |
| `WHITESPACE_ISSUE` | 值前後多了空白（常見於會被拼接使用的欄位，如 URL）| 去除多餘空白，用 `suggestion` 給的去空白版本 |
| `ENCODING_ERROR` | 檔案編碼不是 UTF-8，可能是不小心用錯編輯器另存 | 依 `suggestion` 的 `iconv` 指令轉檔 |
| `YAML_SYNTAX_ERROR` | YAML/JSON 語法壞掉，通常是不小心誤觸換行 | 檢查 `message` 附的行號與該行內容，確認是否該與上一行合併 |
| `POSSIBLE_BROKEN_LINE` | properties 格式裡有一行不符合 `key: value`，很可能是換行殘留 | 檢查是否該與上一行合併 |
| `STRUCTURE_MISMATCH` | 複合分隔格式（如 `A10\|stop,1,0;...`）切出來的欄位數量不對 | 通常是多打或少打一個分隔符號（逗號/分號/直線），對照 `suggestion` 給的預期格式修正 |
| `CONTEXT_PATTERN_MISMATCH` | 在目前的情境參數下（例如 factory=A），這個欄位的值不符合對應規則 | 依 `suggestion` 給的 pattern 修正，通常代表值指向了錯的廠別/情境 |
| `MISSING_CONTEXT_PARAM` | 驗證時沒有帶情境參數，或 schema 要求的情境參數沒提供 | **不要自己猜值**，停下來跟任務發起人確認 |
| `UNDEFINED_FIELD` | config 裡出現 schema 沒定義過的欄位 | 確認是不是打錯欄位名稱；如果這是 release note 要求的新欄位，停下來回報，不要自己決定要不要保留 |

---

## 什麼情況一定要停下來問人，而不是自己決定

1. release note 提到的欄位，在 schema 裡找不到對應規則
2. schema 要求情境參數（`context_params`），但任務描述沒有明確給值
3. 驗證失敗訊息看起來像是 schema 本身定義有問題（例如 enum 清單明顯少了一個合理的值），而不是 config 寫錯——這種情況要回報給開發判斷是否該更新 schema，你不能自己改 schema
4. 重試 3 次仍未通過驗證
5. release note 的說明本身模糊到你無法判斷該填什麼值（不要用猜的填一個「看起來合理」的值蒙混過去）

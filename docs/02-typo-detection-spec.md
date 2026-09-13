# Typo 偵測規格

設計原則：**每一類 typo 都要能被自動偵測，且錯誤訊息必須明確標出「是哪一種問題」以及「正確的參考答案或改善作法」**，而不是只回報「驗證失敗」。

驗證腳本對每個問題都會輸出統一格式：

```
✗ [欄位路徑] 類型：<TYPO 類型代碼>
    目前值：<實際讀到的值>
    問題說明：<用人話講清楚哪裡不對>
    建議修正：<具體的修正建議，能給就給明確值，不能給就給規則依據>
```

以下逐一說明六種常見情境的偵測機制。

---

## 情境 1：value 後多出空白

**風險**：這類 config 常被拿去做字串拼接（例如組出完整 URL），尾端多一個空白會讓拼接後的字串壞掉，但用肉眼看 config 檔案幾乎看不出來。

**偵測機制**：
- 對讀進來的**每一個字串型別的值**（不論有沒有在 schema 裡特別標註），做 `value != value.strip()` 檢查，這是**全域自動檢查**，不需要開發額外設定
- 特別針對會被拼接使用的欄位，schema 可以加註 `used_in_concat: true`，讓錯誤訊息額外提醒「此欄位會被拼接使用，空白影響更大」

**錯誤代碼**：`TRAILING_WHITESPACE` / `LEADING_WHITESPACE`

**範例輸出**：
```
✗ [api_url] 類型：TRAILING_WHITESPACE
    目前值：'https://api.example.com/v1 '（尾端多了 1 個空白字元）
    問題說明：此欄位標記為 used_in_concat，多餘空白會導致下游字串拼接產生錯誤網址
    建議修正：'https://api.example.com/v1'
```

---

## 情境 2：編碼改變導致讀取 ERROR

**風險**：檔案被非預期的編輯器另存成 Big5、GBK 或帶 BOM 的 UTF-8，導致下游服務讀取時直接噴錯，而且通常要到「執行期」才會被發現。

**偵測機制**：
- 驗證腳本在**做任何 YAML/JSON 解析之前**，先讀取檔案的原始 bytes，用 `utf-8` 嚴格模式嘗試 decode
- 若失敗，用編碼偵測（如 `charset-normalizer`）猜測實際編碼，並回報**具體是哪個 byte 位置/哪一行**壞掉
- 這一步是**檔案層級**的檢查，比 YAML 語法檢查更早一關，因為編碼錯的檔案通常連 YAML parser 都無法正確處理，錯誤訊息會很難懂

**錯誤代碼**：`ENCODING_ERROR`

**範例輸出**：
```
✗ [檔案層級] 類型：ENCODING_ERROR
    偵測到的編碼：Big5（預期應為 UTF-8）
    問題說明：檔案無法以 UTF-8 解碼，第 14 行附近出現非法位元組
    建議修正：使用 `iconv -f BIG5 -t UTF-8 config.yaml -o config.yaml` 轉檔後再提交
```

---

## 情境 3：value 的值少了字母或不完整（enum 限定）

**風險**：例如 `active` 打成 `acive`，或 `production` 打成 `Production`（大小寫）。這類錯誤語法上完全合法，只有語意錯，一般 YAML/JSON parser 抓不到。

**偵測機制**：
- schema 裡對該 key 定義 `enum: [...]`，實際值不在清單內就報錯
- **加碼**：用模糊比對（`difflib.get_close_matches`）在 enum 清單中找出最接近的合法值，直接告訴使用者「你是不是要打這個？」，大幅縮短除錯時間

**開發端的配套要求**（對應規格「新 config 設定，開發必須要在驗證的 script config 新增 key 的名稱 & value 的種類」）：
- schema 裡每新增一個 key，必須同時填：
  - `type`（值的種類：string/integer/number/boolean/list）
  - 若為固定選項，填 `enum`
  - `description`（用途說明，給 QA/維運快速理解用）
- 這三項缺一，`--lint-schema` 檢查會直接擋下該 schema PR

**錯誤代碼**：`ENUM_INVALID`

**範例輸出**：
```
✗ [mode] 類型：ENUM_INVALID
    目前值：'acive'
    問題說明：此欄位（廠區運作模式）僅接受固定選項，'acive' 不在合法清單內
    合法值：['active', 'standby']
    建議修正：是否想輸入 'active'？（依相似度自動比對出最接近的合法值）
```

---

## 情境 4：不同廠別／廠區的 URL 情境判斷

**風險**：同一個 key（例如 `api_url`）在廠別 A、廠別 B 底下應該指向不同的網址，維運需要「轉頭」對照另一份文件才知道現在該填哪個，容易點錯、貼錯。

**偵測機制**：
- schema 定義 `context_params`：宣告這個 service 的 config 需要哪些「情境參數」（例如 `factory`，合法值 `A`/`B`）
- 有情境相依性的欄位，用 `context_patterns` 依情境值分別定義合法 pattern
- **執行驗證時，情境參數由人工明確傳入**（`--context factory=A`），不是機器自動猜測——這是刻意設計：情境本身（這次改的是哪個廠）是人為決策，機器只負責「在你告訴我是哪個廠之後，幫你確認值有沒有填對」，減少人「記錯/看錯/轉頭比對時抄錯」的環節
- 若必要的情境參數沒有提供，直接報錯提醒，不會默默略過這項檢查

**錯誤代碼**：`CONTEXT_PATTERN_MISMATCH` / `MISSING_CONTEXT_PARAM`

**範例輸出**：
```
✗ [api_url] 類型：CONTEXT_PATTERN_MISMATCH
    目前情境：factory=A
    目前值：'https://api-b.factory.example.com/v1'
    問題說明：在 factory=A 的情境下，api_url 應指向 A 廠區網址，但目前值符合的是 B 廠區的格式
    建議修正：'https://api-a.factory.example.com/v1'
```

```
✗ [執行層級] 類型：MISSING_CONTEXT_PARAM
    問題說明：schema 定義此 service 需要 factory 情境參數（A 或 B），但執行驗證時未提供
    建議修正：請在指令加上 --context factory=A 或 --context factory=B 後重新執行
```

---

## 情境 5：不小心誤觸換行，導致 YAML/JSON 格式錯誤

**風險**：編輯器誤觸 Enter，把本來一行的內容拆成兩行，YAML/JSON 縮排結構壞掉，輕則直接 parse 失敗，重則「意外變成合法但錯誤」的結構（例如某個值被腰斬，YAML 仍然能解析，但值不完整或多了一個奇怪的 key）。

**偵測機制（兩層）**：

1. **直接解析失敗的情況**：
   - 攔截 `yaml.YAMLError` / `json.JSONDecodeError`，取出例外訊息中的行號（`problem_mark.line`），直接印出**壞掉的那一行內容**，並提示「請檢查是否有不小心換行」
2. **解析成功但結構跑掉的情況**（比較隱蔽）：
   - 這種情況下，換行通常會造成兩種可觀察後果之一，而這兩種都已經被既有機制涵蓋：
     - 原本應該完整的值被腰斬 → 對應欄位不符合 `pattern`/`enum`/`format`，會被一般格式驗證抓到
     - 換行後多出一個不在 schema 定義內的 key（YAML 把斷開的下一行當成新的 key）→ 會被 **strict mode 的「未定義欄位」檢查**抓到
   - 因此換行問題的偵測 = 「YAML 語法錯誤攔截」+「既有的欄位格式與多餘欄位檢查」兩者組合，不需要另外寫特殊邏輯，但錯誤訊息上會明確標註**這類特徵的錯誤很可能來自誤觸換行**，提示使用者往這個方向排查

**錯誤代碼**：`YAML_SYNTAX_ERROR`（直接壞掉）／既有的 `PATTERN_MISMATCH`、`ENUM_INVALID`、`UNDEFINED_FIELD`（隱蔽型，訊息會附加提示）

**範例輸出**：
```
✗ [檔案層級] 類型：YAML_SYNTAX_ERROR
    問題說明：第 9 行縮排或結構有誤，YAML 解析失敗
    錯誤詳情：mapping values are not allowed here
    建議修正：請檢查第 9 行是否有不小心換行或多餘的冒號，對照上一行的縮排層級修正
```

```
✗ [service_name] 類型：PATTERN_MISMATCH
    目前值：'auth-serv'
    問題說明：值不符合格式規則，且長度明顯短於一般命名慣例，可能是換行導致值被腰斬
    建議修正：請確認完整值是否為 'auth-service'，並檢查上一行是否有不小心按到 Enter
```

---

## 情境 6：flat properties 格式（`key: value1,value2`）

**風險**：這類格式沒有 YAML 的巢狀結構保護，一行被誤觸換行後，很容易變成「看起來也是合法一行」但其實內容是錯的，YAML/JSON parser 完全幫不上忙，因為這根本不是拿 YAML/JSON parser 在讀。

**偵測機制**：
- 用專屬的 properties 格式解析器（而非 YAML/JSON parser）：逐行比對是否符合 `key: value1,value2,...` 格式
- 每個 key 對應到 schema 裡的 `item_enum` 或 `item_pattern`，**用逗號拆開後逐一檢查每個子值**
- 針對「這一行看起來不像 `key: ...` 格式」的孤立行（很可能是換行造成的殘留片段），標記為 `POSSIBLE_BROKEN_LINE`，並提示是否應與上一行合併

**錯誤代碼**：`PROPERTIES_ITEM_INVALID` / `POSSIBLE_BROKEN_LINE`

**範例輸出**：
```
✗ [allowed_regions[2]] 類型：PROPERTIES_ITEM_INVALID
    目前值：'us-eas'
    問題說明：此為逗號分隔清單中的第 3 個值，不在合法清單內
    合法值：['us-east', 'us-west', 'ap-southeast']
    建議修正：是否想輸入 'us-east'？

✗ [第 7 行] 類型：POSSIBLE_BROKEN_LINE
    該行內容：'t'
    問題說明：這一行不符合 "key: value" 格式，且內容極短，很可能是上一行不小心換行造成的殘留片段
    建議修正：檢查第 6～7 行，確認是否應合併成一行
```

---

## 情境 7：客製化複合分隔格式（同一個值裡混用多種分隔符號）

**風險**：有些 properties 檔案的一個 value 裡會混用好幾種分隔符號來塞進「多筆記錄 × 多個欄位」的資訊，例如：

```
KeyD: A10|stop,1,0;A11|read,2,5;A88|process,1,23
```

這裡 `;` 分隔多筆設備指令、`|` 分隔設備代號與動作參數、`,` 分隔動作與兩個數值。這種格式沒有 YAML/JSON 的巢狀結構保護，任何一個分隔符號打錯、欄位數量不對、多一個逗號少一個分號，都很難用肉眼看出來,也無法用前面「情境 6」單層 properties 的邏輯處理。

**偵測機制**：
- 引入兩種可以互相巢狀的 schema 積木：
  - `type: list` + `delimiter` + `item`：用 `delimiter` 切開，**筆數不限**，每一份都套用同一份 `item` 規則（適合「同性質的清單」，例如逗號分隔的權限清單）
  - `type: tuple` + `delimiter` + `fields`：用 `delimiter` 切開，**欄位數固定**，依序對應到 `fields` 裡各自的規則（適合「一筆記錄裡有好幾個不同意義的欄位」）
- 這兩種積木可以任意巢狀，對應到 `KeyD` 的結構就是：
  `list(";")` → 每筆是 `tuple("|")`：[設備代號, `tuple(",")`：[動作(enum), 數值1(int), 數值2(int)]]
- 遞迴驗證引擎會自動處理巢狀：切錯層級、欄位數量對不上、子欄位值不合法，都會定位到精確的路徑（例如 `KeyD[1].action_params.action`），而不是只說「這個 key 壞了」

**錯誤代碼**：`STRUCTURE_MISMATCH`（切出來的欄位數量不對）＋ 沿用既有的 `ENUM_INVALID` / `PATTERN_MISMATCH` / `TYPE_MISMATCH` / `WHITESPACE_ISSUE`（套用在每個切出來的子欄位上）

**範例輸出**：
```
✗ [KeyD[1].action_params.action] 類型：ENUM_INVALID
    目前值：'reads'
    問題說明：值不在合法清單內
    建議修正：是否想輸入 'read'？（合法值：['stop', 'start', 'read', 'process']）

✗ [KeyD[2].action_params.param2] 類型：TYPE_MISMATCH
    目前值：'23,99'
    問題說明：型別錯誤，預期為 integer，但 '23,99' 無法轉換為數字
    （這通常代表多打了一個逗號，導致這一筆的欄位數量比預期多一個）
```

**設計提醒**：這類 schema 描述的是「這個 key 的值本身是一份小型的巢狀資料結構」，本質上跟情境 1-6 是同一套 dot-path 規則系統的延伸，並非另外一套邏輯——`list`/`tuple` 積木寫好之後，`enum`/`pattern`/`format`/`min`/`max`/空白檢查全部都能直接套用在切出來的每個子欄位上，不需要為每個新的客製 key 特別寫程式碼，只要在 schema 裡描述好切分規則即可。

## 總覽對照表

| 情境 | 錯誤代碼 | 偵測時機 | 是否需要人工提供額外資訊 |
|---|---|---|---|
| 尾端/前端空白 | `TRAILING_WHITESPACE` / `LEADING_WHITESPACE` | 解析後，全欄位自動掃描 | 否 |
| 編碼錯誤 | `ENCODING_ERROR` | 解析前，檔案層級 | 否 |
| enum 值錯誤/不完整 | `ENUM_INVALID` | 逐欄位規則比對 | 否 |
| 廠別情境 URL 錯誤 | `CONTEXT_PATTERN_MISMATCH` / `MISSING_CONTEXT_PARAM` | 逐欄位規則比對 | **是，需 `--context factory=A/B`** |
| 換行造成格式錯誤 | `YAML_SYNTAX_ERROR` + 既有格式檢查 | 解析中 / 解析後 | 否 |
| properties 多值格式錯誤 | `PROPERTIES_ITEM_INVALID` / `POSSIBLE_BROKEN_LINE` | 專屬 parser 逐行/逐值檢查 | 否 |
| 客製化複合分隔格式（多層分隔符號） | `STRUCTURE_MISMATCH` + 沿用既有格式檢查 | 依 schema 描述的 list/tuple 結構遞迴檢查 | 否 |
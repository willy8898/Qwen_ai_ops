# Config 驗證腳本 v2 使用說明

對應《docs/02-typo-detection-spec.md》六種常見手動改 config 的 typo 情境，逐一實作偵測邏輯。

## 安裝
```bash
pip install pyyaml charset-normalizer
```

## 用法

**單一 service、單一檔案：**
```bash
python3 validate_config.py --schemas-dir schemas --service service-a \
  --config path/to/config.yaml --context factory=A
```

**批次檢查資料夾（同一個 service）：**
```bash
python3 validate_config.py --schemas-dir schemas --service service-a \
  --config-dir configs/service-a/ --context factory=A
```
> 注意：`--config-dir` 底下的所有檔案會用同一份 schema 驗證，因此資料夾內請只放同一個 service 的 config。不同 service 請分開執行，或參考文件《01-workflow-design.md》裡提到的 manifest 批次驗證延伸做法。

**只指定單一 schema 檔（不透過 --service 機制）：**
```bash
python3 validate_config.py --schema schemas/service-a.schema.yaml --config config.yaml
```

**列出目前有哪些 service（agent 想知道有哪些 schema 可用時直接跑這個）：**
```bash
python3 validate_config.py --schemas-dir schemas --list-services
```

**給 agent/程式解析用的結構化輸出（加 `--json`，任何驗證指令都可以加這個參數）：**
```bash
python3 validate_config.py --schemas-dir schemas --service service-a \
  --config config.yaml --context factory=A --json
```
會輸出單一 JSON 物件到 stdout，例如：
```json
{
  "passed": false,
  "results": [
    {
      "file": "config.yaml",
      "passed": false,
      "errors": [
        {"path": "mode", "code": "ENUM_INVALID", "message": "值不在合法清單內",
         "current_value": "acive", "suggestion": "是否想輸入 'active'？（合法值：['active', 'standby']）"}
      ]
    }
  ]
}
```
不加 `--json` 就是預設的人類可讀文字報告（前面章節看到的格式）。這支腳本設計上就是給任何 agent CLI 用內建 shell 工具直接執行的，不需要額外包裝，見《04-mcp-implementation-guide.md》。

**檢查 schema 本身是否完整（給 schema PR 用，CI 應該掛在 schema 變更的 pipeline 上）：**
```bash
python3 validate_config.py --schema schemas/service-a.schema.yaml --lint-schema
```

**flat properties 格式（自動依副檔名 `.properties` 判斷，也可用 `--format properties` 強制指定）：**
```bash
python3 validate_config.py --schemas-dir schemas --service service-b \
  --config app.properties
```

回傳值：`0` 全部通過／`1` 有任何一項失敗，方便接 CI。

---

## 六種情境的實測結果（examples/ 目錄）

| 情境 | 測試檔案 | 執行結果 |
|---|---|---|
| 1. 尾端多空白 | `case1-trailing-whitespace.yaml` | ✗ `WHITESPACE_ISSUE`，並標注此欄位有拼接風險 |
| 2. 編碼錯誤 | `case2-encoding-error.yaml`（Big5 編碼） | ✗ `ENCODING_ERROR`，附上 `iconv` 轉檔指令 |
| 3. enum typo | `case3-enum-typo.yaml`（`acive`） | ✗ `ENUM_INVALID`，模糊比對建議 `active` |
| 4. 廠別 context 錯誤 | `case4-wrong-factory-url.yaml` | ✗ `CONTEXT_PATTERN_MISMATCH`（在 `--context factory=A` 下 URL 指向 B 廠） |
| 4b. 未提供情境參數 | 同上，不帶 `--context` | ✗ `MISSING_CONTEXT_PARAM`，提示要加什麼參數 |
| 5. 換行造成 YAML 壞掉 | `case5-broken-yaml.yaml` | ✗ `YAML_SYNTAX_ERROR`，附上行號與該行內容 |
| 6. properties 多值 + 換行殘留 | `case6-properties-broken.properties` | ✗ 同時抓到 `POSSIBLE_BROKEN_LINE` 與 `ENUM_INVALID`（`us-wes` → 建議 `us-west`） |
| 正常範例 | `service-a-good.yaml` | ✓ 通過所有檢查 |

實際執行畫面（節錄）：

```
$ python3 validate_config.py --schemas-dir schemas --service service-a \
    --config examples/case3-enum-typo.yaml --context factory=A

檢查檔案：examples/case3-enum-typo.yaml
  發現 1 個問題：
✗ [mode] 類型：ENUM_INVALID
    目前值：'acive'
    問題說明：值不在合法清單內
    建議修正：是否想輸入 'active'？（合法值：['active', 'standby']）

============================================================
驗證失敗，請根據上方「建議修正」逐項處理後再提交
```

```
$ python3 validate_config.py --schemas-dir schemas --service service-a \
    --config examples/case4-wrong-factory-url.yaml --context factory=A

檢查檔案：examples/case4-wrong-factory-url.yaml
  發現 1 個問題：
✗ [api_url] 類型：CONTEXT_PATTERN_MISMATCH
    目前值：'https://api-b.factory.example.com/v1'
    問題說明：在 factory=A 的情境下，此欄位不符合對應規則
    建議修正：應符合 pattern：^https://api-a\.factory\.example\.com/v1$
```

## 情境 7：客製化複合分隔格式（多層分隔符號）

例如：
```
KeyD: A10|stop,1,0;A11|read,2,5;A88|process,1,23
```

schema 用兩種可以互相巢狀的積木描述：

```yaml
KeyD:
  type: list          # 用 delimiter 切開，筆數不限，每份套用同一份 item 規則
  delimiter: ";"
  item:
    type: tuple        # 用 delimiter 切開，欄位數固定，依序對應到 fields
    delimiter: "|"
    fields:
      - name: device_id
        type: string
        pattern: '^[A-Z][0-9]{1,3}$'
      - name: action_params
        type: tuple      # tuple 裡面可以再放 tuple，任意巢狀
        delimiter: ","
        fields:
          - name: action
            type: string
            enum: [stop, start, read, process]
          - name: param1
            type: integer
            min: 0
          - name: param2
            type: integer
            min: 0
```

實測（`examples/case7-custom-good.properties`／`case7-custom-bad.properties`，schema 見 `schemas/custom-device-config.schema.yaml`）：

```bash
$ python3 validate_config.py --schema schemas/custom-device-config.schema.yaml \
    --config examples/case7-custom-bad.properties

✗ [KeyA] 類型：WHITESPACE_ISSUE
    目前值：'http://perform.fab100-a.comp.com/api/v1 '
    ...
✗ [keyB] 類型：TYPE_MISMATCH
    目前值：'12a4'
    ...
✗ [keyC[1]] 類型：ENUM_INVALID
    目前值：'Wrte'
    建議修正：是否想輸入 'Write'？
✗ [KeyD[1].action_params.action] 類型：ENUM_INVALID
    目前值：'reads'
    建議修正：是否想輸入 'read'？
✗ [KeyD[2].action_params.param2] 類型：TYPE_MISMATCH
    目前值：'23,99'（多打了一個逗號，欄位數量對不上）
✗ [keyE[1].server_name] 類型：PATTERN_MISMATCH
    目前值：'Server_B'
✗ [keyE[1].state] 類型：ENUM_INVALID
    目前值：'started'
    建議修正：是否想輸入 'start'？
```

七個問題全部抓到，且都定位到精確的子欄位路徑。

## 已知限制
- 換行造成的 YAML 語法錯誤，回報的行號是 **PyYAML 偵測到異常的位置**，不一定精準對應到「實際不小心按下 Enter」的那一行，通常會落在附近 1-2 行內，建議連同上下文一起檢查
- `--config-dir` 目前假設資料夾內都是同一個 service 的 config；跨 service 批次驗證請參考文件 01 提到的 manifest 延伸設計（目前尚未實作，屬於後續擴充項目）
- 陣列的巢狀深度目前完整支援一層（`a.[].b`），若有雙層陣列巢狀（`a.[].b.[].c`）需要再擴充 `resolve_paths` 邏輯
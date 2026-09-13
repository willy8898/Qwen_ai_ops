# Config 修改任務規則

## 專案結構
- 各 service 的規則定義在 `validator/schemas/{service}.schema.yaml`
- 目前可用的 service：`service-fab-a`、`service-fab-b`（跑 `python3 validator/validate_config.py --schemas-dir validator/schemas --list-services` 可即時確認清單，不要憑記憶假設）
- 驗證腳本是 `validator/validate_config.py`

## 角色邊界（務必遵守）
- 只能修改 config 檔案本身，**不可修改 `validator/schemas/*.schema.yaml`**。release note 提到 schema 裡沒有的欄位，停下來回報，交由開發人員決定是否新增，不可以自己猜一個規則套用
- 不可修改任何非 config 的程式碼檔案
- 情境參數（例如 `factory` 廠別）必須由任務發起人明確提供，不可以自行猜測或套用預設值；任務描述沒提供就停下來詢問
- 重試 3 次仍無法通過驗證，不可以硬開 PR，必須停下來回報卡住的具體錯誤內容

## 修改 config 前
1. 先用 `cat validator/schemas/{service}.schema.yaml` 讀出這個 service 的規則，了解有哪些合法欄位、enum、格式，不要憑經驗猜測
2. 如果 schema 裡有 `context_params`（例如 factory 廠別），這個值必須由任務發起人在任務描述中明確提供；如果沒有提供，停下來詢問，不可以自己猜一個值套用

## 修改完 config 之後，必須執行驗證
用以下指令驗證（把 `{service}`、`{config_path}`、`{context}` 換成實際值）：

```bash
python3 validator/validate_config.py \
  --schemas-dir validator/schemas --service {service} \
  --config {config_path} --context factory={factory}
```

- 退出碼 0 代表全部通過
- 退出碼非 0 代表有問題，畫面上每一項都會列出「類型」「目前值」「問題說明」「建議修正」，請照著建議修正後重新執行這條指令
- 如果想要結構化的 JSON 結果方便自己解析，可以加上 `--json` 參數
- 最多重試 3 次；3 次後仍未通過，停下來回報具體卡住的錯誤內容，不要為了通過驗證硬塞一個格式合法但語意可疑的值

## 開 PR 前
把最後一次驗證通過的完整輸出，貼進 PR 說明的「驗證結果」區塊，並依照 `agent_skill/SKILL.md` 的 PR 說明模板整理內容。
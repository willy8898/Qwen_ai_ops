# Release Note 8 - Modify the bug of Service A

## PBI
- http://ticket.Z_corp.com/ticker_system/55688

## Background
- 過去由於欄位限制，最多只能讓user 輸入5 種rules，造成多rules 時，需要開多張單子，耗時且關聯比對複雜
- 基於產能需求，將欄位上限提高到50 個rules 來調整整體user 使用效率

## Scope
- 僅針對Service A 的 Create_rules 做變數擴充
- 新增子table 作為所有rules 的細節儲存，不變動到母table，減少對現有訂單的影響

## Test report
- http://note_site.Z_corp.com/123541/


## Code
| RU / Service name | Branch / Version | Sponsor |
|---|---|---|
| Service A | master / 2.0.1-00 | @王曉明 |

## Config

| Config name | Type | Sample value | Remark |
|---|---|---|---|
| new_feature_switch | New | Y | 此為新功能開關，需要根據廠區需求開啟，預設為N。現行只有確定a 廠區需要此功能，其餘廠區須詢問sponsor |
| max_rule_num | New | 20 | rules 的最大上限，超過會報400。a 廠區設定為50，b 廠區設定20，其餘廠區須詢問sponsor |
| functions | Edit | ...,new_feature_switch,max_rule_num | 既有functions 需要新增此config 設定，否則會認不得這兩個new config，特別注意! |
| ServiceB_url | New | http://serviceB-stg-dev.dev.Tcomp.com/ | 需要根據廠區類別與所在環境修改修改，例如: Fab99 a 廠區的prod 環境，需改成 http://serviceB-a.f99.Tcomp.com/ |
| ServiceB_port | New | 8888 | 需要根據廠區類別與所在環境修改修改，例如: Fab99 a 廠區的prod 環境，需改成 http://serviceB-a.f99.Tcomp.com/ |
| ServiceB_port | New | 8888 | 需要根據廠區類別與所在環境修改修改，請參考下表 |
| ServiceB_pname | New | task/api/v2/delete | pname 設定 for ServiceB |
| old_serviceB_port  | Delete | - | 移除對應舊的serviceB 設定 |
| old_serviceB_url   | Delete | - | 移除對應舊的serviceB 設定 |
| old_serviceB_pname | Delete | - | 移除對應舊的serviceB 設定 |

- port 廠區對應

| Fab | port |
|---|---|
| F99 | 8888 |
| F98 | 8080 |
| F97 | 8080 |
| abc | 9999 |


## Change procedure
1. 先新增子table RULE_DETAILS_RUNTIME & RULE_DETAILS_HIS
2. Service 進版
3. 通知前端開啟前端config


## Sanity check
1. [IT 可測]
- 執行以下SQL ，確認資料寫入正確
~~~
select * from user1.RULE_DETAILS_RUNTIME where ruleid <> '' with ur;
~~~

- 執行以下SQL ，確認資料寫入正確
~~~
select * from user1.RULE_DETAILS_HIS where ruleid <> '' with ur;
~~~

2. [IT 可測]
- 檢查Monitor: VM基本指標正常
http://Grafana.com/VM_monitor_board

- 檢查Monitor: 檢查訂單量正常
http://Grafana.com/Order_count_board

3. [User end-to-end 測試功能]
- 請user 協助開單，部署人員撈DB 觀察中文無亂碼
~~~
select * from user1.RULE_DETAILS_RUNTIME where ruleid = '{Date_訂單編號}' with ur;
~~~
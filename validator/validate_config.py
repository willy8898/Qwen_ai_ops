#!/usr/bin/env python3
"""
Config 驗證腳本 v2
==================
對應規格：
  1. value 尾端/前端多餘空白（含拼接風險標記 used_in_concat）
  2. 編碼錯誤導致讀取失敗（檔案層級，解析前檢查）
  3. enum 合法值檢查 + 模糊比對建議（typo 修正提示）
  4. 廠別/廠區等「情境參數」相依的格式檢查（--context 由人工提供）
  5. 誤觸換行造成的 YAML/JSON 格式錯誤（含行號定位）
  6. flat properties 格式（key: value1,value2）的專屬解析與逐值檢查

每個 schema 對應一個 service，用 --schemas-dir + --service 指定，
方便多個 service 各自維護自己的規則檔。

回傳值：0 = 全部通過；1 = 有任何一項失敗（可直接接 CI）
"""

import argparse
import glob
import json
import re
import sys
from difflib import get_close_matches
from pathlib import Path

import yaml

try:
    from charset_normalizer import from_bytes as _detect_charset
except ImportError:
    _detect_charset = None


# --------------------------------------------------------------------------
# 內建常用 format
# --------------------------------------------------------------------------
BUILTIN_FORMATS = {
    "ipv4": r"^(\d{1,3}\.){3}\d{1,3}$",
    "hostname": r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$",
    "email": r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    "semver": r"^\d+\.\d+\.\d+$",
    "url": r"^https?://[^\s]+$",
}

TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "list": list,
    "dict": (dict,),
}


class ValidationError:
    def __init__(self, path, code, message, current_value=None, suggestion=None):
        self.path = path
        self.code = code
        self.message = message
        self.current_value = current_value
        self.suggestion = suggestion

    def __str__(self):
        lines = [f"✗ [{self.path}] 類型：{self.code}"]
        if self.current_value is not None:
            lines.append(f"    目前值：{self.current_value!r}")
        lines.append(f"    問題說明：{self.message}")
        if self.suggestion:
            lines.append(f"    建議修正：{self.suggestion}")
        return "\n".join(lines)


# ==========================================================================
# 情境 2：編碼檢查（檔案層級，解析前）
# ==========================================================================
def check_encoding(filepath):
    with open(filepath, "rb") as f:
        raw = f.read()
    try:
        raw.decode("utf-8")
        return None
    except UnicodeDecodeError as e:
        detected = None
        if _detect_charset is not None:
            try:
                best = _detect_charset(raw).best()
                detected = best.encoding if best else None
            except Exception:
                detected = None
        line_no = raw[: e.start].count(b"\n") + 1
        detected_display = detected.upper() if detected else "<未知，請用編輯器另存為 UTF-8 試試>"
        return ValidationError(
            "檔案層級",
            "ENCODING_ERROR",
            f"檔案無法以 UTF-8 解碼，第 {line_no} 行附近出現非法位元組"
            + (f"，偵測到的編碼可能是 {detected}" if detected else ""),
            suggestion=f"使用指令轉檔：iconv -f {detected_display} -t UTF-8 {filepath} -o {filepath}",
        )


# ==========================================================================
# 情境 5：YAML/JSON 語法錯誤（含行號定位）
# ==========================================================================
def load_structured(filepath, fmt):
    """回傳 (data, error)；error 不為 None 時 data 必為 None"""
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            if fmt == "json":
                return json.load(f), None
            return yaml.safe_load(f), None
    except yaml.YAMLError as e:
        line = None
        if getattr(e, "problem_mark", None) is not None:
            line = e.problem_mark.line + 1
        content_line = lines[line - 1].rstrip("\n") if line and 1 <= line <= len(lines) else None
        detail = getattr(e, "problem", str(e))
        msg = f"第 {line} 行附近解析失敗：{detail}"
        if content_line is not None:
            msg += f"（該行內容：{content_line!r}）"
        return None, ValidationError(
            "檔案層級",
            "YAML_SYNTAX_ERROR",
            msg,
            suggestion="請檢查該行是否有不小心換行、多餘冒號，或縮排層級與上一行不一致",
        )
    except json.JSONDecodeError as e:
        content_line = lines[e.lineno - 1].rstrip("\n") if 1 <= e.lineno <= len(lines) else None
        msg = f"第 {e.lineno} 行、第 {e.colno} 欄解析失敗：{e.msg}"
        if content_line is not None:
            msg += f"（該行內容：{content_line!r}）"
        return None, ValidationError(
            "檔案層級",
            "YAML_SYNTAX_ERROR",
            msg,
            suggestion="請檢查該行是否有不小心換行、多餘逗號，或括號未閉合",
        )


# ==========================================================================
# 情境 6：flat properties 格式（key: value1,value2）專屬解析器
# ==========================================================================
def parse_properties(filepath):
    errors = []
    data = {}
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    last_key = None
    for i, raw_line in enumerate(lines, start=1):
        # 注意：這裡只去掉行尾的換行符號，刻意不對整行做 strip()。
        # 如果整行先 strip 掉，value 尾端的空白（情境 1 要抓的那種 typo）
        # 會在解析階段就被吃掉，之後永遠驗不出來。
        line = raw_line.rstrip("\n").rstrip("\r")
        stripped_for_check = line.strip()
        if not stripped_for_check or stripped_for_check.startswith("#"):
            continue

        m = re.match(r"^([A-Za-z0-9_.\-]+)\s*:[ \t]?(.*)$", line)
        if m:
            key = m.group(1)
            # 值本身保留原始內容（含可能的尾端空白），是否要用某個分隔符號
            # 切分（逗號/分號/直線等）交給 schema 的 delimiter + item/fields
            # 規則決定，因為客製 properties 常常一個值裡混用好幾種分隔符號，
            # 寫死在 parser 裡反而會切錯。
            data[key] = m.group(2)
            last_key = key
        else:
            hint = ""
            if last_key and len(stripped_for_check) < 15:
                hint = f"，且內容長度異常短，很可能是上一行（key: {last_key}）不小心換行造成的殘留片段"
            errors.append(
                ValidationError(
                    f"第 {i} 行",
                    "POSSIBLE_BROKEN_LINE",
                    f"這一行不符合 'key: value' 格式{hint}",
                    current_value=stripped_for_check,
                    suggestion=f"檢查這一行是否應與上一行（第 {i - 1} 行, key: {last_key}）合併",
                )
            )
    return data, errors


# ==========================================================================
# 情境 1：全欄位空白掃描（不論 schema 是否有定義都會檢查）
# ==========================================================================
def scan_whitespace(data, display_path, norm_path, errors, used_in_concat_norms):
    if isinstance(data, dict):
        for k, v in data.items():
            scan_whitespace(
                v,
                f"{display_path}.{k}" if display_path else k,
                f"{norm_path}.{k}" if norm_path else k,
                errors,
                used_in_concat_norms,
            )
    elif isinstance(data, list):
        for i, v in enumerate(data):
            scan_whitespace(
                v,
                f"{display_path}[{i}]",
                f"{norm_path}.[]" if norm_path else "[]",
                errors,
                used_in_concat_norms,
            )
    elif isinstance(data, str):
        leading = data != data.lstrip()
        trailing = data != data.rstrip()
        if leading or trailing:
            side = []
            if leading:
                side.append("前端")
            if trailing:
                side.append("尾端")
            note = ""
            if norm_path in used_in_concat_norms:
                note = "；此欄位標記為 used_in_concat，多餘空白會導致下游字串拼接產生錯誤結果"
            errors.append(
                ValidationError(
                    display_path,
                    "WHITESPACE_ISSUE",
                    f"字串{'/'.join(side)}含有多餘空白{note}",
                    current_value=data,
                    suggestion=repr(data.strip()),
                )
            )


def collect_used_in_concat_norms(rules):
    return {path for path, rule in rules.items() if rule.get("used_in_concat")}


# ==========================================================================
# dot-path 解析（支援 [] 代表遍歷 list）
# ==========================================================================
def resolve_paths(data, parts, current_path=""):
    if not parts:
        return [(current_path, data, True)]
    part, rest = parts[0], parts[1:]

    if part == "[]":
        if isinstance(data, list):
            results = []
            for i, item in enumerate(data):
                results.extend(resolve_paths(item, rest, f"{current_path}[{i}]"))
            return results
        return [(current_path + "[]", None, False)]

    if isinstance(data, dict) and part in data:
        new_path = f"{current_path}.{part}" if current_path else part
        return resolve_paths(data[part], rest, new_path)

    new_path = f"{current_path}.{part}" if current_path else part
    return [(new_path, None, False)]


def check_type(value, expected_type):
    py_type = TYPE_MAP.get(expected_type)
    if py_type is None:
        return True
    if expected_type in ("integer", "number") and isinstance(value, bool):
        return False
    return isinstance(value, py_type)


# ==========================================================================
# 情境 7：客製化複合分隔格式（同一個值裡混用多種分隔符號，例如
#         "A10|stop,1,0;A11|read,2,5" 這種 ";" 分多筆、"|" 分欄位、
#         "," 分子欄位的巢狀結構）
#
# schema 用兩種積木描述任意巢狀深度：
#   type: list   + delimiter + item    → 用 delimiter 切開，每一份都套用同一份 item 規則（筆數不固定）
#   type: tuple  + delimiter + fields  → 用 delimiter 切開，依序對應到固定的 fields（欄位數固定、each 可不同規則）
# 兩種積木可以互相巢狀，item/fields 裡的每一項本身也可以再是一個 list/tuple。
# ==========================================================================
def validate_leaf(value, spec, path, errors, context):
    """驗證單一個「不能再往下切」的值（字串/數字），並做型別轉換。"""
    raw_value = value
    if isinstance(raw_value, str) and raw_value != raw_value.strip():
        errors.append(
            ValidationError(
                path,
                "WHITESPACE_ISSUE",
                "字串前後含有多餘空白（複合格式中分隔符號旁邊多打的空白很容易造成下游解析錯位）",
                current_value=raw_value,
                suggestion=repr(raw_value.strip()),
            )
        )

    value = value.strip() if isinstance(value, str) else value
    expected_type = spec.get("type", "string")

    if expected_type in ("integer", "number") and isinstance(value, str):
        try:
            value = int(value) if expected_type == "integer" else float(value)
        except ValueError:
            errors.append(
                ValidationError(
                    path,
                    "TYPE_MISMATCH",
                    f"型別錯誤，預期為 {expected_type}，但 {value!r} 無法轉換為數字",
                    current_value=raw_value,
                )
            )
            return

    enum = spec.get("enum")
    if enum is not None and value not in enum:
        match = get_close_matches(str(value), [str(e) for e in enum], n=1, cutoff=0.4)
        suggestion = f"是否想輸入 {match[0]!r}？（合法值：{enum}）" if match else f"合法值：{enum}"
        errors.append(
            ValidationError(path, "ENUM_INVALID", "值不在合法清單內", current_value=value, suggestion=suggestion)
        )

    pattern = spec.get("pattern")
    if pattern is not None and isinstance(value, str) and not re.fullmatch(pattern, value):
        errors.append(
            ValidationError(path, "PATTERN_MISMATCH", "值不符合格式規則", current_value=value, suggestion=f"應符合：{pattern}")
        )

    fmt = spec.get("format")
    if fmt is not None and isinstance(value, str):
        fmt_pattern = BUILTIN_FORMATS.get(fmt)
        if fmt_pattern and not re.fullmatch(fmt_pattern, value):
            errors.append(ValidationError(path, "FORMAT_MISMATCH", f"值不符合 {fmt} 格式", current_value=value))

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "min" in spec and value < spec["min"]:
            errors.append(ValidationError(path, "RANGE_ERROR", f"值小於最小值 {spec['min']}", current_value=value))
        if "max" in spec and value > spec["max"]:
            errors.append(ValidationError(path, "RANGE_ERROR", f"值大於最大值 {spec['max']}", current_value=value))


def validate_leaf_or_composite(value, spec, path, errors, context):
    if isinstance(value, str) and spec.get("delimiter") and (spec.get("item") or spec.get("fields")):
        validate_composite(value, spec, path, errors, context)
    else:
        validate_leaf(value, spec, path, errors, context)


def validate_composite(value, spec, path, errors, context):
    if not isinstance(value, str):
        errors.append(ValidationError(path, "TYPE_MISMATCH", f"預期為可切割的字串，實際為 {type(value).__name__}"))
        return

    delimiter = spec.get("delimiter", ",")
    spec_type = spec.get("type")

    # ---- list：筆數不固定，每一份都套用同一份 item 規則 ----
    if spec_type == "list" and "item" in spec:
        parts = value.split(delimiter)
        if "min_items" in spec and len(parts) < spec["min_items"]:
            errors.append(
                ValidationError(
                    path,
                    "STRUCTURE_MISMATCH",
                    f"以 '{delimiter}' 分隔後只有 {len(parts)} 筆，預期至少 {spec['min_items']} 筆",
                    current_value=value,
                )
            )
        for i, part in enumerate(parts):
            validate_leaf_or_composite(part, spec["item"], f"{path}[{i}]", errors, context)
        return

    # ---- tuple：欄位數固定，依序對應到 fields，每個欄位可以有自己的規則 ----
    if spec_type == "tuple" and "fields" in spec:
        fields = spec["fields"]
        parts = value.split(delimiter, maxsplit=len(fields) - 1)
        if len(parts) != len(fields):
            errors.append(
                ValidationError(
                    path,
                    "STRUCTURE_MISMATCH",
                    f"欄位數量不符，預期用 '{delimiter}' 切出 {len(fields)} 個欄位，實際切出 {len(parts)} 個",
                    current_value=value,
                    suggestion=f"預期格式：{delimiter.join(f['name'] for f in fields)}；請確認是否遺漏或多了分隔符號 '{delimiter}'",
                )
            )
            return
        for part, field_spec in zip(parts, fields):
            field_name = field_spec.get("name", "")
            child_path = f"{path}.{field_name}" if field_name else path
            validate_leaf_or_composite(part, field_spec, child_path, errors, context)
        return

    # 沒有合法的 list/tuple 定義，當一般 leaf 處理
    validate_leaf(value, spec, path, errors, context)


# ==========================================================================
# 情境 3：enum 檢查 + 模糊比對建議 / 一般格式驗證 / 情境 4：context_patterns
# ==========================================================================
def validate_rule(path, value, exists, rule, errors, context):
    required = rule.get("required", False)

    if not exists:
        if required:
            errors.append(ValidationError(path, "MISSING_REQUIRED", "必填欄位缺漏"))
        return

    # 情境 7：客製化複合分隔格式，交給專屬的遞迴引擎處理，其餘一般檢查不再重複跑
    if isinstance(value, str) and rule.get("delimiter") and (rule.get("item") or rule.get("fields")):
        validate_composite(value, rule, path, errors, context)
        return

    expected_type = rule.get("type")

    # properties 檔案讀出來的數值一律是字串，這裡先嘗試轉型，轉型失敗才視為型別錯誤，
    # 讓 "type: integer" 這種宣告不用因為資料來源是 properties 而額外繞路用 pattern 檢查數字
    if expected_type in ("integer", "number") and isinstance(value, str):
        try:
            value = int(value.strip()) if expected_type == "integer" else float(value.strip())
        except ValueError:
            pass  # 轉型失敗就維持原字串，讓下面的 check_type 正常報 TYPE_MISMATCH

    if expected_type and not check_type(value, expected_type):
        errors.append(
            ValidationError(
                path,
                "TYPE_MISMATCH",
                f"型別錯誤，預期為 {expected_type}，實際為 {type(value).__name__}",
                current_value=value,
                suggestion=f"請確認值的型別應為 {expected_type}",
            )
        )
        return

    # 空白問題已經在 scan_whitespace 全域掃描報過一次了，這裡後續的
    # enum/pattern/format 檢查一律用去除頭尾空白後的值來判斷，
    # 避免同一個「多打了空白」的根因被重複報成兩種不同錯誤造成雜訊
    if isinstance(value, str):
        value = value.strip()

    enum = rule.get("enum")
    if enum is not None and value not in enum:
        match = get_close_matches(str(value), [str(e) for e in enum], n=1, cutoff=0.4)
        suggestion = f"是否想輸入 {match[0]!r}？（合法值：{enum}）" if match else f"合法值：{enum}"
        errors.append(
            ValidationError(path, "ENUM_INVALID", "值不在合法清單內", current_value=value, suggestion=suggestion)
        )

    pattern = rule.get("pattern")
    if pattern is not None and isinstance(value, str) and not re.fullmatch(pattern, value):
        errors.append(
            ValidationError(
                path, "PATTERN_MISMATCH", "值不符合格式規則", current_value=value, suggestion=f"應符合正規表達式：{pattern}"
            )
        )

    fmt = rule.get("format")
    if fmt is not None and isinstance(value, str):
        fmt_pattern = BUILTIN_FORMATS.get(fmt)
        if fmt_pattern and not re.fullmatch(fmt_pattern, value):
            errors.append(
                ValidationError(path, "FORMAT_MISMATCH", f"值不符合 {fmt} 格式", current_value=value)
            )

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "min" in rule and value < rule["min"]:
            errors.append(
                ValidationError(path, "RANGE_ERROR", f"值小於最小值 {rule['min']}", current_value=value)
            )
        if "max" in rule and value > rule["max"]:
            errors.append(
                ValidationError(path, "RANGE_ERROR", f"值大於最大值 {rule['max']}", current_value=value)
            )

    if isinstance(value, list):
        item_pattern = rule.get("item_pattern")
        item_enum = rule.get("item_enum")
        for i, item in enumerate(value):
            item_path = f"{path}[{i}]"
            item_str = item.strip() if isinstance(item, str) else item
            if item_pattern and isinstance(item, str) and not re.fullmatch(item_pattern, item_str):
                errors.append(
                    ValidationError(
                        item_path, "PATTERN_MISMATCH", "值不符合格式規則", current_value=item, suggestion=f"應符合：{item_pattern}"
                    )
                )
            if item_enum is not None and item_str not in item_enum:
                match = get_close_matches(str(item_str), [str(e) for e in item_enum], n=1, cutoff=0.4)
                suggestion = f"是否想輸入 {match[0]!r}？（合法值：{item_enum}）" if match else f"合法值：{item_enum}"
                errors.append(
                    ValidationError(item_path, "ENUM_INVALID", "值不在合法清單內", current_value=item, suggestion=suggestion)
                )

    # ---- 情境 4：情境相依格式檢查（例如廠別 A/B 對應不同 URL）----
    context_patterns = rule.get("context_patterns")
    if context_patterns:
        for param_name, value_pattern_map in context_patterns.items():
            ctx_value = context.get(param_name)
            if ctx_value is None:
                errors.append(
                    ValidationError(
                        path,
                        "MISSING_CONTEXT_PARAM",
                        f"此欄位規則相依於情境參數 '{param_name}'，但執行時未提供，無法確認此值是否正確",
                        suggestion=f"請加上 --context {param_name}=<值> 後重新執行",
                    )
                )
                continue
            expected_pattern = value_pattern_map.get(ctx_value)
            if expected_pattern is None:
                errors.append(
                    ValidationError(
                        path,
                        "INVALID_CONTEXT_VALUE",
                        f"提供的情境參數 {param_name}={ctx_value} 不在 schema 定義範圍內",
                        suggestion=f"合法情境值：{list(value_pattern_map.keys())}",
                    )
                )
                continue
            if isinstance(value, str) and not re.fullmatch(expected_pattern, value.strip()):
                errors.append(
                    ValidationError(
                        path,
                        "CONTEXT_PATTERN_MISMATCH",
                        f"在 {param_name}={ctx_value} 的情境下，此欄位不符合對應規則",
                        current_value=value,
                        suggestion=f"應符合 pattern：{expected_pattern}",
                    )
                )


def validate_context_params(ruleset, context, errors):
    for cp in ruleset.get("context_params", []):
        name = cp["name"]
        if name not in context:
            if cp.get("required"):
                errors.append(
                    ValidationError(
                        "執行層級",
                        "MISSING_CONTEXT_PARAM",
                        f"schema 定義此 service 需要情境參數 '{name}'"
                        + (f"（{cp['description']}）" if cp.get("description") else "")
                        + "，但執行驗證時未提供",
                        suggestion=f"請在指令加上 --context {name}=<值>，合法值：{cp.get('enum')}",
                    )
                )
        else:
            val = context[name]
            enum = cp.get("enum")
            if enum and val not in enum:
                errors.append(
                    ValidationError(
                        "執行層級",
                        "INVALID_CONTEXT_VALUE",
                        f"提供的情境參數 {name}={val} 不在合法範圍",
                        suggestion=f"合法值：{enum}",
                    )
                )


# ==========================================================================
# strict mode：規則沒定義過的多餘欄位
# ==========================================================================
def collect_defined_dict_children(rules):
    allowed = {}
    for path in rules.keys():
        parts = path.split(".")
        parent = ""
        for part in parts:
            if part == "[]":
                break
            allowed.setdefault(parent, set()).add(part)
            parent = f"{parent}.{part}" if parent else part
    return allowed


def check_extra_keys(data, allowed, current_path, errors):
    if not isinstance(data, dict):
        return
    allowed_keys = allowed.get(current_path)
    if allowed_keys is not None:
        for key in data.keys():
            if key not in allowed_keys:
                full_path = f"{current_path}.{key}" if current_path else key
                errors.append(
                    ValidationError(full_path, "UNDEFINED_FIELD", "出現規則中未定義的欄位（可能是多打或打錯字）")
                )
    for key, value in data.items():
        check_extra_keys(value, allowed, f"{current_path}.{key}" if current_path else key, errors)


# ==========================================================================
# 主驗證流程
# ==========================================================================
def validate_config_data(config_data, ruleset, context):
    errors = []
    rules = ruleset.get("rules", {})

    validate_context_params(ruleset, context, errors)

    used_in_concat_norms = collect_used_in_concat_norms(rules)
    scan_whitespace(config_data, "", "", errors, used_in_concat_norms)

    for path, rule in rules.items():
        resolved = resolve_paths(config_data, path.split("."))
        if not resolved:
            if rule.get("required"):
                errors.append(ValidationError(path, "MISSING_REQUIRED", "必填欄位缺漏"))
            continue
        for actual_path, value, exists in resolved:
            validate_rule(actual_path, value, exists, rule, errors, context)

    if ruleset.get("strict", False):
        allowed = collect_defined_dict_children(rules)
        check_extra_keys(config_data, allowed, "", errors)

    return errors


def detect_format(filepath, forced_format=None):
    if forced_format and forced_format != "auto":
        return forced_format
    ext = Path(filepath).suffix.lower()
    if ext == ".json":
        return "json"
    if ext in (".properties",):
        return "properties"
    return "yaml"


def collect_file_result(config_path, ruleset, context, forced_format=None):
    """
    驗證單一檔案，回傳結構化結果（不印任何東西），格式：
      {"file": ..., "passed": bool, "errors": [{"path","code","message","current_value","suggestion"}, ...]}
    文字模式（run_single_file）跟 --json 模式都呼叫這個函式，確保兩種輸出方式
    背後跑的是同一套驗證邏輯，不會有「文字模式抓得到、json 模式抓不到」的落差。
    """
    fmt = detect_format(config_path, forced_format)

    enc_error = check_encoding(config_path)
    if enc_error:
        return {"file": config_path, "passed": False, "errors": [_error_to_dict(enc_error)]}

    if fmt == "properties":
        config_data, parse_errors = parse_properties(config_path)
    else:
        config_data, parse_error = load_structured(config_path, fmt)
        parse_errors = [parse_error] if parse_error else []

    if parse_errors and config_data is None:
        return {"file": config_path, "passed": False, "errors": [_error_to_dict(e) for e in parse_errors]}

    if config_data is None:
        return {
            "file": config_path,
            "passed": False,
            "errors": [{"path": "檔案層級", "code": "EMPTY_FILE", "message": "檔案內容為空", "current_value": None, "suggestion": None}],
        }

    errors = list(parse_errors)
    errors.extend(validate_config_data(config_data, ruleset, context))

    return {"file": config_path, "passed": len(errors) == 0, "errors": [_error_to_dict(e) for e in errors]}


def _error_to_dict(e):
    return {"path": e.path, "code": e.code, "message": e.message, "current_value": e.current_value, "suggestion": e.suggestion}


def run_single_file(config_path, ruleset, context, forced_format=None):
    """文字模式：印出人類看的報告，回傳 True/False。"""
    print(f"\n檢查檔案：{config_path}")
    result = collect_file_result(config_path, ruleset, context, forced_format)

    if result["passed"]:
        print("  ✓ 通過所有檢查")
        return True

    print(f"  發現 {len(result['errors'])} 個問題：")
    for err in result["errors"]:
        e = ValidationError(err["path"], err["code"], err["message"], err["current_value"], err["suggestion"])
        print(e)
    return False


# ==========================================================================
# schema 自我檢查（--lint-schema，給 schema PR 用）
# ==========================================================================
def lint_schema(ruleset):
    problems = []
    declared_context_names = {cp["name"] for cp in ruleset.get("context_params", [])}

    for path, rule in ruleset.get("rules", {}).items():
        if not rule.get("description"):
            problems.append(f"[{path}] 缺少 description，QA/維運無法從 schema 得知此欄位用途")
        if "type" not in rule:
            problems.append(f"[{path}] 缺少 type 定義")
        if "enum" in rule and not rule["enum"]:
            problems.append(f"[{path}] enum 清單為空")
        for pname in rule.get("context_patterns", {}):
            if pname not in declared_context_names:
                problems.append(f"[{path}] context_patterns 使用了未在 context_params 宣告的情境參數 '{pname}'")

    for cp in ruleset.get("context_params", []):
        if "description" not in cp:
            problems.append(f"[context_params.{cp.get('name')}] 缺少 description")
        if not cp.get("enum"):
            problems.append(f"[context_params.{cp.get('name')}] 缺少合法值 enum 定義")

    return problems


def load_ruleset(args):
    if args.schema:
        return load_structured(args.schema, "yaml")[0]
    schema_path = Path(args.schemas_dir) / f"{args.service}.schema.yaml"
    if not schema_path.exists():
        print(f"找不到 service '{args.service}' 對應的 schema：{schema_path}")
        sys.exit(1)
    return load_structured(str(schema_path), "yaml")[0]


def parse_context(context_args):
    context = {}
    for item in context_args or []:
        if "=" not in item:
            print(f"--context 參數格式錯誤：{item}，應為 key=value")
            sys.exit(1)
        k, v = item.split("=", 1)
        context[k] = v
    return context


def main():
    parser = argparse.ArgumentParser(description="Config 驗證腳本 v2")
    schema_group = parser.add_mutually_exclusive_group()
    schema_group.add_argument("--schema", help="單一規則定義檔路徑")
    schema_group.add_argument("--schemas-dir", help="多 service 規則檔所在資料夾，需搭配 --service（或搭配 --list-services 列出所有 service）")
    parser.add_argument("--service", help="service 名稱，對應 {schemas-dir}/{service}.schema.yaml")

    parser.add_argument("--list-services", action="store_true", help="列出 --schemas-dir 底下所有可用的 service 名稱，不做任何驗證")
    parser.add_argument("--lint-schema", action="store_true", help="檢查 schema 本身是否完整（description/enum 等），不驗證 config")

    config_group = parser.add_mutually_exclusive_group()
    config_group.add_argument("--config", help="單一 config 檔案路徑")
    config_group.add_argument("--config-dir", help="批次檢查資料夾內所有 config 檔")

    parser.add_argument("--format", default="auto", choices=["auto", "yaml", "json", "properties"], help="config 格式，預設依副檔名自動判斷")
    parser.add_argument("--context", action="append", help="情境參數，格式 key=value，可重複給多個，例如 --context factory=A")
    parser.add_argument("--json", action="store_true", help="輸出單一 JSON 物件到 stdout，取代人類可讀的文字報告（給 agent/程式解析用）")

    args = parser.parse_args()

    if args.list_services:
        if not args.schemas_dir:
            parser.error("--list-services 必須搭配 --schemas-dir")
        services = sorted(p.stem.replace(".schema", "") for p in Path(args.schemas_dir).glob("*.schema.yaml"))
        if args.json:
            print(json.dumps({"services": services}, ensure_ascii=False, indent=2))
        else:
            for s in services:
                print(s)
        sys.exit(0)

    if not args.schema and not args.schemas_dir:
        parser.error("請提供 --schema 或 --schemas-dir（或用 --list-services 只列出可用 service）")
    if args.schemas_dir and not args.service:
        parser.error("使用 --schemas-dir 時必須搭配 --service")

    ruleset = load_ruleset(args)

    if args.lint_schema:
        problems = lint_schema(ruleset)
        if args.json:
            print(json.dumps({"passed": not problems, "problems": problems}, ensure_ascii=False, indent=2))
            sys.exit(0 if not problems else 1)
        if not problems:
            print("✓ schema 檢查通過，所有欄位皆有完整定義")
            sys.exit(0)
        print(f"schema 檢查發現 {len(problems)} 個問題：")
        for p in problems:
            print(f"  ✗ {p}")
        sys.exit(1)

    if not args.config and not args.config_dir:
        parser.error("請提供 --config 或 --config-dir（或改用 --lint-schema 只檢查規則檔本身）")

    context = parse_context(args.context)

    if args.config:
        targets = [args.config]
    else:
        targets = sorted(
            glob.glob(f"{args.config_dir}/**/*.yaml", recursive=True)
            + glob.glob(f"{args.config_dir}/**/*.yml", recursive=True)
            + glob.glob(f"{args.config_dir}/**/*.json", recursive=True)
            + glob.glob(f"{args.config_dir}/**/*.properties", recursive=True)
        )
        if not targets:
            if args.json:
                print(json.dumps({"passed": False, "error": f"在 {args.config_dir} 找不到任何 config 檔案"}, ensure_ascii=False))
            else:
                print(f"在 {args.config_dir} 找不到任何 config 檔案")
            sys.exit(1)

    if args.json:
        results = [collect_file_result(t, ruleset, context, args.format) for t in targets]
        all_passed = all(r["passed"] for r in results)
        print(json.dumps({"passed": all_passed, "results": results}, ensure_ascii=False, indent=2))
        sys.exit(0 if all_passed else 1)

    all_passed = True
    for target in targets:
        passed = run_single_file(target, ruleset, context, args.format)
        all_passed = all_passed and passed

    print("\n" + "=" * 60)
    if all_passed:
        print(f"全部 {len(targets)} 個檔案驗證通過 ✓")
        sys.exit(0)
    print("驗證失敗，請根據上方「建議修正」逐項處理後再提交")
    sys.exit(1)


if __name__ == "__main__":
    main()
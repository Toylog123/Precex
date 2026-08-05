#!/usr/bin/env python3
# PreCex - harness/llm_client.py 多提供商 LLM API 统一封装（token 记账强制）
# 作者：Toylog | 版本：v0.2 | 功能概述：OpenAI 兼容 /chat/completions 调用封装（含 Anthropic 原生适配）：
#   真实调用与 mock 双模式，自动记录 in/out token 与费用到 experiments/runs/token_ledger.jsonl；
#   内置 TokenLedger 读取/汇总，供 scripts/token_accounting.py 与管线自测使用。
#   纯标准库实现（urllib），无第三方依赖，设计在 WSL Python 3.10+ 内运行。
#
# v0.2（2026-08-04）多提供商扩展（P2 多 LLM 可解释性评分前置）：
#   - PROVIDERS 注册表：minimax（默认）/ deepseek / openai / gemini（OpenAI 兼容端点）/ anthropic（原生格式）
#   - 每提供商独立 env key、base_url、model、计价；env 可用 <PROVIDER>_BASE_URL / <PROVIDER>_MODEL 覆盖
#   - LLMClient(provider="deepseek") 直接切换；缺 key 时真实调用抛错（configured_providers() 可预检）
#   - 账本每行新增 provider 字段；旧账本无该字段，读取时兼容缺省
#   - DeepSeek 模型 deepseek-v4-flash（DeepSeek-V4-Flash-0731，官方 Models & Pricing 页确认 2026-08-04），
#     OpenAI 兼容端点 https://api.deepseek.com/v1；计价 输入 $0.14/1M、输出 $0.28/1M

"""多提供商调研结论（存档）：
- MiniMax M3：端点（OpenAI 兼容）https://api.minimaxi.com/v1；模型 MiniMax-M3（上下文 1,000,000 token）。
  计费参考（占位，待平台账单校准）：输入 $0.60 / 1M token、输出 $2.40 / 1M token；>512K 翻倍。
- DeepSeek V4-Flash（2026-08-04 官方 Models & Pricing 页）：模型 deepseek-v4-flash（版本 DeepSeek-V4-Flash-0731），
  OpenAI 兼容 base_url https://api.deepseek.com/v1；1M 上下文、最大输出 384K；
  计价 输入 $0.14 / 1M（cache miss）、输出 $0.28 / 1M。
- 调用路径（OpenAI 兼容）：POST {base_url}/chat/completions，Authorization: Bearer <key>。
- 多模态输入：messages 的 content 支持内容块数组；图片用 {"type":"image_url",...}。
- Thinking 控制：MiniMax 传 "reasoning_split": true 可把思考分离到 reasoning_details 字段。
"""

import json
import os
import signal
import socket
import sys
import time
import uuid
from datetime import datetime, timezone
from urllib import error as urllib_error
from urllib import request as urllib_request

# ---- 提供商注册表 ----------------------------------------------------------
PROVIDERS = {
    "minimax": {
        "label": "MiniMax",
        "env_key": "MINIMAX_API_KEY",
        "base_url": "https://api.minimaxi.com/v1",
        "model": "MiniMax-M3",
        "input_price": 0.60,
        "output_price": 2.40,
        "native": False,
    },
    "deepseek": {
        "label": "DeepSeek",
        "env_key": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-flash",
        "input_price": 0.14,
        "output_price": 0.28,
        "native": False,
    },
    "openai": {
        "label": "OpenAI",
        "env_key": "OPENAI_API_KEY",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o",
        "input_price": 2.50,
        "output_price": 10.00,
        "native": False,
    },
    "gemini": {
        "label": "Gemini",
        "env_key": "GEMINI_API_KEY",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-2.0-flash",
        "input_price": 0.10,
        "output_price": 0.40,
        "native": False,
    },
    "anthropic": {
        "label": "Anthropic",
        "env_key": "ANTHROPIC_API_KEY",
        "base_url": "https://api.anthropic.com/v1",
        "model": "claude-sonnet-4-20250514",
        "input_price": 3.00,
        "output_price": 15.00,
        "native": True,
    },
}
DEFAULT_PROVIDER = "minimax"

# 默认端点 / 模型 / 网络参数（向后兼容旧构造参数默认值）
DEFAULT_BASE_URL = PROVIDERS[DEFAULT_PROVIDER]["base_url"]
DEFAULT_MODEL = PROVIDERS[DEFAULT_PROVIDER]["model"]
DEFAULT_TIMEOUT = 120.0
DEFAULT_MAX_RETRIES = 3

# 价格占位（USD / 百万 token，随 provider 切换；以平台账单为准待校准）
DEFAULT_INPUT_TOKEN_PRICE = PROVIDERS[DEFAULT_PROVIDER]["input_price"]
DEFAULT_OUTPUT_TOKEN_PRICE = PROVIDERS[DEFAULT_PROVIDER]["output_price"]

# 仓库根与账本默认路径（experiments/runs/ 不入库，见 .gitignore 约定）
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_LEDGER_PATH = os.path.join(REPO_ROOT, "experiments", "runs", "token_ledger.jsonl")
ENV_KEY = PROVIDERS[DEFAULT_PROVIDER]["env_key"]


def _load_env_file(env_path=None):
    """解析仓库根 .env（KEY=VALUE 每行，跳过 # 注释与空行），返回 dict；文件不存在返回 {}。"""
    path = env_path or os.path.join(REPO_ROOT, ".env")
    data = {}
    if not os.path.isfile(path):
        return data
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def configured_providers(env_path=None):
    """返回已配置 key 的 provider 列表（.env 或环境变量任一存在即算）。"""
    env = _load_env_file(env_path)
    out = []
    for pid, p in PROVIDERS.items():
        key = env.get(p["env_key"]) or os.environ.get(p["env_key"]) or ""
        if key:
            out.append(pid)
    return out


def _new_session():
    """生成会话标识：优先环境变量 PRECEX_SESSION（整批实验统一标识），否则进程级随机 id。"""
    s = os.environ.get("PRECEX_SESSION")
    if s:
        return s
    return "%s-%s" % (datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"), uuid.uuid4().hex[:6])


class LLMClient:
    """多提供商客户端：真实 / mock 双模式 + token 记账强制（所有调用自动入账本）。

    构造参数：provider（默认 minimax；可选 deepseek/openai/gemini/anthropic）、
    api_key（默认 .env > 环境变量）、base_url、model、temperature、timeout、max_retries、
    mock、input_token_price / output_token_price、ledger_path、session。
    base_url/model 未显式传入时用 provider 默认（可被 <PROVIDER>_BASE_URL/<PROVIDER>_MODEL 覆盖）。
    """

    def __init__(self, api_key=None, base_url=None, model=None,
                 temperature=0.2, timeout=DEFAULT_TIMEOUT, max_retries=DEFAULT_MAX_RETRIES,
                 mock=False, input_token_price=None, output_token_price=None,
                 ledger_path=DEFAULT_LEDGER_PATH, session=None, provider=None):
        self.provider = provider or DEFAULT_PROVIDER
        if self.provider not in PROVIDERS:
            raise ValueError("未知 provider=%r，可选：%s" % (self.provider, ", ".join(sorted(PROVIDERS))))
        pconf = PROVIDERS[self.provider]
        env = _load_env_file()
        self.provider_label = pconf["label"]
        # api_key 优先级：显式参数 > 仓库根 .env > 环境变量
        self.api_key = api_key or env.get(pconf["env_key"]) or os.environ.get(pconf["env_key"]) or ""
        # base_url/model 优先级：显式参数 > env 覆盖 > provider 默认
        env_prefix = self.provider.upper()
        env_base = env.get(env_prefix + "_BASE_URL") or os.environ.get(env_prefix + "_BASE_URL") or ""
        env_model = env.get(env_prefix + "_MODEL") or os.environ.get(env_prefix + "_MODEL") or ""
        self.base_url = (base_url or env_base or pconf["base_url"]).rstrip("/")
        self.model = model or env_model or pconf["model"]
        self.temperature = temperature
        self.timeout = timeout
        self.max_retries = max_retries
        self.mock = mock
        self.input_token_price = float(input_token_price if input_token_price is not None else pconf["input_price"])
        self.output_token_price = float(output_token_price if output_token_price is not None else pconf["output_price"])
        self.native = bool(pconf.get("native", False))
        self.ledger_path = ledger_path or DEFAULT_LEDGER_PATH
        self.session = session or _new_session()

    # ---- 对外接口 ----------------------------------------------------------

    def chat(self, messages, temperature=None, tag=None, **kw):
        """调用聊天补全接口（OpenAI 兼容或 Anthropic 原生）。

        返回统一 dict：{"content": str, "input_tokens": int, "output_tokens": int,
        "cost": float, "raw": dict|None, "mode": "real"|"mock"}。
        - kw 为透传的 API 附加字段（如 max_tokens / reasoning_split / tools / top_p）；
        - tag 为记账用途标识（如 "cex_semantize" / "repair_patch"），仅入账本，不透传。
        - 多模态预留：messages 的 content 可带 image_url / video_url 内容块（见文件头调研结论）。
        """
        if not isinstance(messages, list) or not messages:
            raise ValueError("messages 必须是非空列表（[{role, content}, ...]）")
        if self.mock:
            # mock 模式：不真实调用，同样记账并标记 mode=mock
            res = self._mock_chat(messages)
            self._record(res["input_tokens"], res["output_tokens"], res["cost"], "mock", tag)
            return res
        # 组装请求体：核心字段固定，附加字段透传（不允许覆盖 model/messages/temperature）
        payload = {"model": self.model, "messages": messages}
        temp = self.temperature if temperature is None else temperature
        if temp is not None:
            payload["temperature"] = temp
        for k in ("model", "messages", "temperature"):
            kw.pop(k, None)
        payload.update(kw)
        content, raw, in_tok, out_tok = self._call_api(payload)
        cost = self._cost(in_tok, out_tok)
        self._record(in_tok, out_tok, cost, "real", tag)
        return {"content": content, "input_tokens": in_tok, "output_tokens": out_tok,
                "cost": cost, "raw": raw, "mode": "real"}

    def text_generate(self, prompt, system=None, **kw):
        """便捷方法：包装 messages=[{system}, {user}] 后调用 chat（kw 同 chat，含 tag）。"""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return self.chat(messages, **kw)

    # ---- 内部实现 ----------------------------------------------------------

    def _post_json(self, url, headers, body, timeout):
        """POST + 指数退避重试（≤max_retries）；429/5xx 重试，4xx 不重试。返回解析后的 JSON。"""
        last_err = None
        for attempt in range(self.max_retries + 1):
            req = urllib_request.Request(url, data=body, headers=headers, method="POST")
            def _alarm_handler(signum, frame):
                raise socket.timeout("wall-clock timeout %.0fs exceeded" % (timeout + 10))
            old_handler = None
            try:
                old_handler = signal.getsignal(signal.SIGALRM)
                signal.signal(signal.SIGALRM, _alarm_handler)
                signal.alarm(int(timeout) + 10)
            except Exception:
                pass  # 非主线程/无 signal 环境降级为 urllib 自身超时
            try:
                try:
                    with urllib_request.urlopen(req, timeout=timeout) as resp:
                        try:
                            return json.loads(resp.read().decode("utf-8"))
                        except ValueError as e:
                            raise RuntimeError("%s API 响应非合法 JSON：%s" % (self.provider_label, e))
                except urllib_error.HTTPError as e:
                    # 429/5xx：可重试，指数退避后继续
                    if (e.code == 429 or e.code >= 500) and attempt < self.max_retries:
                        time.sleep(min(1.5 * (2 ** attempt), 20.0))
                        continue
                    detail = e.read().decode("utf-8", errors="replace")[:500]
                    if e.code == 429 or e.code >= 500:
                        raise RuntimeError(
                            "%s API 服务错误(HTTP %d)，重试 %d 次后仍失败：%s"
                            % (self.provider_label, e.code, self.max_retries, detail))
                    # 4xx（401/403 等）：不重试，提示检查 key
                    raise RuntimeError(
                        "%s API 请求被拒(HTTP %d)：%s\n提示：请检查 %s 是否正确、"
                        "账户额度/权限是否可用。"
                        % (self.provider_label, e.code, detail, PROVIDERS[self.provider]["env_key"]))
                except (urllib_error.URLError, socket.timeout, TimeoutError) as e:
                    # 网络层错误（DNS/连接超时/socket 读超时/墙钟 alarm 等）：可重试
                    last_err = getattr(e, "reason", e)
                    if attempt < self.max_retries:
                        time.sleep(min(1.5 * (2 ** attempt), 20.0))
                        continue
            finally:
                try:
                    signal.alarm(0)
                    if old_handler is not None:
                        signal.signal(signal.SIGALRM, old_handler)
                except Exception:
                    pass

        raise RuntimeError("%s API 网络错误，重试 %d 次后仍失败：%s"
                           % (self.provider_label, self.max_retries, last_err))

    def _call_api(self, payload):
        """真实调用：Anthropic 走原生 /messages，其余走 OpenAI 兼容 /chat/completions。

        返回 (content, raw, input_tokens, output_tokens)。
        """
        if not self.api_key:
            raise RuntimeError(
                "未配置 %s（%s：环境变量或仓库根 .env），无法发起真实调用；"
                "离线调试请用 mock 模式（LLMClient(mock=True) 或 --self-test）。"
                % (PROVIDERS[self.provider]["env_key"], self.provider_label))
        headers = {"Content-Type": "application/json", "Authorization": "Bearer " + self.api_key}
        if self.native:
            return self._call_anthropic_api(payload, headers)
        url = self.base_url + "/chat/completions"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        data = self._post_json(url, headers, body, self.timeout)
        return self._parse_response(data)

    def _call_anthropic_api(self, payload, headers):
        """Anthropic 原生 /messages 适配：拆出 system、必填 max_tokens、解析 content 块。"""
        url = self.base_url + "/messages"
        headers = dict(headers)
        headers["x-api-key"] = self.api_key
        headers["anthropic-version"] = "2023-06-01"
        system = "\n".join(
            m.get("content", "") for m in payload.get("messages", [])
            if m.get("role") == "system" and isinstance(m.get("content"), str))
        messages = [m for m in payload.get("messages", []) if m.get("role") != "system"]
        body_dict = {
            "model": payload.get("model", self.model),
            "max_tokens": int(payload.get("max_tokens", 4096)),
            "messages": messages,
        }
        if "temperature" in payload:
            body_dict["temperature"] = payload["temperature"]
        if system:
            body_dict["system"] = system
        for k, v in payload.items():
            if k not in ("model", "messages", "temperature", "max_tokens"):
                body_dict[k] = v
        body = json.dumps(body_dict, ensure_ascii=False).encode("utf-8")
        data = self._post_json(url, headers, body, self.timeout)
        return self._parse_anthropic_response(data)

    @staticmethod
    def _parse_response(data):
        """从 OpenAI 兼容响应提取 content 与 token 用量；content 为列表时统一拼接 text 块。"""
        try:
            msg = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            raise RuntimeError("OpenAI 兼容响应缺少 choices[0].message：%s" % str(data)[:500])
        content = msg.get("content") or ""
        if isinstance(content, list):
            content = "".join(seg.get("text", "") for seg in content if isinstance(seg, dict))
        usage = data.get("usage") or {}
        return content, data, usage.get("prompt_tokens") or 0, usage.get("completion_tokens") or 0

    @staticmethod
    def _parse_anthropic_response(data):
        """从 Anthropic 原生响应提取 content 与 token 用量。"""
        try:
            content = "".join(blk.get("text", "") for blk in data.get("content", [])
                              if isinstance(blk, dict))
        except (KeyError, TypeError):
            raise RuntimeError("Anthropic 响应缺少 content 块：%s" % str(data)[:500])
        usage = data.get("usage") or {}
        return content, data, usage.get("input_tokens") or 0, usage.get("output_tokens") or 0

    def _mock_chat(self, messages):
        """mock 实现：回显消息摘要 + 简单规则响应（便于管线自测与离线调试）。"""
        last_user = ""
        for m in reversed(messages):
            if m.get("role") == "user" and m.get("content"):
                c = m["content"]
                # 多模态内容块：只取 text 段
                if isinstance(c, list):
                    c = " ".join(seg.get("text", "") for seg in c
                                 if isinstance(seg, dict) and seg.get("type") == "text")
                if isinstance(c, str) and c.strip():
                    last_user = c.strip()
                    break
        summary = last_user[:120] or "<无 user 文本（如纯图像输入）>"
        content = "[mock] 收到 %d 条消息；最后 user 摘要：%s" % (len(messages), summary)
        in_tok = self._estimate_tokens(messages)
        out_tok = max(1, len(content) // 4)
        return {"content": content, "input_tokens": in_tok, "output_tokens": out_tok,
                "cost": self._cost(in_tok, out_tok), "raw": None, "mode": "mock"}

    @staticmethod
    def _estimate_tokens(messages):
        """粗略估算 token 数（字符数/4，中英混合够记账展示用），真实调用以 usage 为准。"""
        total = 0
        for m in messages:
            c = m.get("content") or ""
            if isinstance(c, list):
                c = " ".join(seg.get("text", "") for seg in c if isinstance(seg, dict))
            total += len(c) // 4 + 1
        return max(1, total)

    def _cost(self, in_tok, out_tok):
        """费用 = in*输入单价/1M + out*输出单价/1M（USD）。"""
        return (in_tok * self.input_token_price + out_tok * self.output_token_price) / 1_000_000.0

    def _record(self, input_tokens, output_tokens, cost, mode, tag):
        """把一次调用追加到账本（自动创建目录），返回账本行 dict。"""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "provider": self.provider_label,
            "model": self.model,
            "input_tokens": int(input_tokens),
            "output_tokens": int(output_tokens),
            "cost": round(float(cost), 8),
            "session": self.session,
            "tag": tag or "",
            "mode": mode,
        }
        os.makedirs(os.path.dirname(self.ledger_path) or ".", exist_ok=True)
        with open(self.ledger_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry


class TokenLedger:
    """token 账本读取与汇总（供 scripts/token_accounting.py 与审计使用）。"""

    def __init__(self, path=DEFAULT_LEDGER_PATH):
        self.path = path

    def read(self):
        """读取账本全部记录（list[dict]）；文件不存在返回 []，损坏行跳过并容错。"""
        if not os.path.isfile(self.path):
            return []
        rows = []
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # 跳过损坏行，不阻塞整体汇总
        return rows

    def summary(self):
        """汇总：调用次数（real/mock 分组）、总 in/out token、总费用。"""
        rows = self.read()
        total_in = sum(r.get("input_tokens") or 0 for r in rows)
        total_out = sum(r.get("output_tokens") or 0 for r in rows)
        total_cost = sum(r.get("cost") or 0.0 for r in rows)
        return {"path": self.path, "calls": len(rows),
                "real_calls": sum(1 for r in rows if r.get("mode") == "real"),
                "mock_calls": sum(1 for r in rows if r.get("mode") == "mock"),
                "total_input_tokens": total_in, "total_output_tokens": total_out,
                "total_tokens": total_in + total_out, "total_cost": round(total_cost, 8)}


def self_test(real=False, provider=None):
    """自检：跑一次 chat（mock 或真实）+ 记账 + 打印 summary，验证管线通。"""
    client = LLMClient(mock=not real, provider=provider)
    res = client.chat(
        messages=[
            {"role": "system", "content": "你是 PreCex 的 RTL 验证助手。"},
            {"role": "user", "content": "演示：请说明形式验证反例在缺陷定位中的作用。"},
        ],
        tag="self-test",
    )
    print("[self-test] provider=%s mode=%s" % (client.provider, res["mode"]))
    print("[self-test] content=%s" % res["content"][:200])
    print("[self-test] in=%d out=%d cost=%.6f" % (res["input_tokens"], res["output_tokens"], res["cost"]))
    s = TokenLedger(client.ledger_path).summary()
    print("[self-test] ledger=%s" % client.ledger_path)
    print("[self-test] summary=%s" % json.dumps(s, ensure_ascii=False))
    return 0


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    # 无参数：打印用法
    if not argv:
        print(__doc__)
        print("用法：python3 llm_client.py [--self-test [--provider X] [--real]]")
        return 1
    provider = None
    if "--provider" in argv:
        provider = argv[argv.index("--provider") + 1]
    if "--self-test" in argv:
        return self_test(real=("--real" in argv), provider=provider)
    if "--self-test-real" in argv:
        return self_test(real=True, provider=provider)
    print("未知参数：%s" % " ".join(argv), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())

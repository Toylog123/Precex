#!/usr/bin/env python3
# PreCex - harness/llm_client.py MiniMax M3 API 统一封装（token 记账强制）
# 作者：Toylog | 版本：v0.1 | 功能概述：OpenAI 兼容 /chat/completions 调用封装：
#   真实调用与 mock 双模式，自动记录 in/out token 与费用到 experiments/runs/token_ledger.jsonl；
#   内置 TokenLedger 读取/汇总，供 scripts/token_accounting.py 与管线自测使用。
#   纯标准库实现（urllib），无第三方依赖，设计在 WSL Python 3.10+ 内运行。

"""MiniMax M3 调研结论（2026-08-03，写入文件头注释存档）：
- 端点（OpenAI 兼容）：国内 https://api.minimaxi.com/v1 ；海外 https://api.minimax.io/v1 。
  （国内平台文档 platform.minimaxi.com、海外平台文档 platform.minimax.io，均确认该 base_url）
- 模型 ID：MiniMax-M3（上下文 1,000,000 token，最新 M 系列：Agent 推理/工具调用/代码/长上下文）。
- 调用路径：POST {base_url}/chat/completions，请求头 Authorization: Bearer <key>，
  Content-Type: application/json。
- 多模态输入：messages 的 content 支持内容块数组；图片用
  {"type": "image_url", "image_url": {"url": "..."}}（detail 可取 low/default/high，
  可用 max_long_side_pixel 控制），视频用 {"type": "video_url", ...}。供 T1 视觉通道使用。
- Thinking 控制：原生返回时 content 内带 <think> 标签（多轮对话需完整保留 assistant 消息）；
  传 "reasoning_split": true 可把思考分离到 reasoning_details 字段。
- 计费参考（占位，待平台账单校准）：输入 $0.60 / 1M token、输出 $2.40 / 1M token；
  上下文超过 512K 时翻倍（$1.20 / $4.80）。可用 input_token_price / output_token_price 覆盖。
"""

import json
import os
import socket
import sys
import time
import uuid
from datetime import datetime, timezone
from urllib import error as urllib_error
from urllib import request as urllib_request

# 默认端点 / 模型 / 网络参数（构造参数可覆盖）
DEFAULT_BASE_URL = "https://api.minimaxi.com/v1"  # 国内端点；海外可改 https://api.minimax.io/v1
DEFAULT_MODEL = "MiniMax-M3"
DEFAULT_TIMEOUT = 120.0
DEFAULT_MAX_RETRIES = 3

# 价格占位（USD / 百万 token，2026-06 发布价；>512K 上下文翻倍，以平台账单为准待校准）
DEFAULT_INPUT_TOKEN_PRICE = 0.60
DEFAULT_OUTPUT_TOKEN_PRICE = 2.40

# 仓库根与账本默认路径（experiments/runs/ 不入库，见 .gitignore 约定）
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_LEDGER_PATH = os.path.join(REPO_ROOT, "experiments", "runs", "token_ledger.jsonl")
ENV_KEY = "MINIMAX_API_KEY"


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


def _new_session():
    """生成会话标识：优先环境变量 PRECEX_SESSION（整批实验统一标识），否则进程级随机 id。"""
    s = os.environ.get("PRECEX_SESSION")
    if s:
        return s
    return "%s-%s" % (datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"), uuid.uuid4().hex[:6])


class LLMClient:
    """MiniMax M3 客户端：真实 / mock 双模式 + token 记账强制（所有调用自动入账本）。

    构造参数：api_key（默认 .env > 环境变量 MINIMAX_API_KEY）、base_url、model、
    temperature、timeout、max_retries、mock、input_token_price / output_token_price、
    ledger_path（账本路径）、session（会话标识，供跨进程归并）。
    """

    def __init__(self, api_key=None, base_url=DEFAULT_BASE_URL, model=DEFAULT_MODEL,
                 temperature=0.2, timeout=DEFAULT_TIMEOUT, max_retries=DEFAULT_MAX_RETRIES,
                 mock=False, input_token_price=DEFAULT_INPUT_TOKEN_PRICE,
                 output_token_price=DEFAULT_OUTPUT_TOKEN_PRICE,
                 ledger_path=DEFAULT_LEDGER_PATH, session=None):
        # api_key 优先级：显式参数 > 仓库根 .env > 环境变量
        env = _load_env_file()
        self.api_key = api_key or env.get(ENV_KEY) or os.environ.get(ENV_KEY) or ""
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.model = model or DEFAULT_MODEL
        self.temperature = temperature
        self.timeout = timeout
        self.max_retries = max_retries
        self.mock = mock
        self.input_token_price = float(input_token_price)
        self.output_token_price = float(output_token_price)
        self.ledger_path = ledger_path or DEFAULT_LEDGER_PATH
        self.session = session or _new_session()

    # ---- 对外接口 ----------------------------------------------------------

    def chat(self, messages, temperature=None, tag=None, **kw):
        """调用 OpenAI 兼容 /chat/completions。

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

    def _call_api(self, payload):
        """真实 HTTP 调用：网络错误 / 5xx / 429 指数退避重试（≤max_retries）；4xx 不重试直接报错。

        返回 (content, raw, input_tokens, output_tokens)。
        """
        if not self.api_key:
            raise RuntimeError(
                "未配置 MINIMAX_API_KEY（环境变量或仓库根 .env），无法发起真实调用；"
                "离线调试请用 mock 模式（LLMClient(mock=True) 或 --self-test）。")
        url = self.base_url + "/chat/completions"
        headers = {"Content-Type": "application/json", "Authorization": "Bearer " + self.api_key}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        last_err = None
        for attempt in range(self.max_retries + 1):
            req = urllib_request.Request(url, data=body, headers=headers, method="POST")
            try:
                with urllib_request.urlopen(req, timeout=self.timeout) as resp:
                    try:
                        data = json.loads(resp.read().decode("utf-8"))
                    except ValueError as e:
                        raise RuntimeError("MiniMax API 响应非合法 JSON：%s" % e)
                return self._parse_response(data)
            except urllib_error.HTTPError as e:
                # 429/5xx：可重试，指数退避后继续
                if (e.code == 429 or e.code >= 500) and attempt < self.max_retries:
                    time.sleep(min(1.5 * (2 ** attempt), 20.0))
                    continue
                detail = e.read().decode("utf-8", errors="replace")[:500]
                if e.code == 429 or e.code >= 500:
                    raise RuntimeError(
                        "MiniMax API 服务错误(HTTP %d)，重试 %d 次后仍失败：%s"
                        % (e.code, self.max_retries, detail))
                # 4xx（401/403 等）：不重试，提示检查 key
                raise RuntimeError(
                    "MiniMax API 请求被拒(HTTP %d)：%s\n提示：请检查 MINIMAX_API_KEY 是否正确、"
                    "账户额度/权限是否可用。" % (e.code, detail))
            except (urllib_error.URLError, socket.timeout, TimeoutError) as e:
                # 网络层错误（DNS/连接超时/socket 读超时等）：可重试
                last_err = getattr(e, "reason", e)
                if attempt < self.max_retries:
                    time.sleep(min(1.5 * (2 ** attempt), 20.0))
                    continue
        raise RuntimeError("MiniMax API 网络错误，重试 %d 次后仍失败：%s" % (self.max_retries, last_err))

    @staticmethod
    def _parse_response(data):
        """从 OpenAI 兼容响应提取 content 与 token 用量；content 为列表时统一拼接 text 块。"""
        try:
            msg = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            raise RuntimeError("MiniMax API 响应缺少 choices[0].message：%s" % str(data)[:500])
        content = msg.get("content") or ""
        if isinstance(content, list):
            content = "".join(seg.get("text", "") for seg in content if isinstance(seg, dict))
        usage = data.get("usage") or {}
        return content, data, usage.get("prompt_tokens") or 0, usage.get("completion_tokens") or 0

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


def self_test(real=False):
    """自检：跑一次 chat（mock 或真实）+ 记账 + 打印 summary，验证管线通。"""
    client = LLMClient(mock=not real)
    res = client.chat(
        messages=[
            {"role": "system", "content": "你是 PreCex 的 RTL 验证助手。"},
            {"role": "user", "content": "演示：请说明形式验证反例在缺陷定位中的作用。"},
        ],
        tag="self-test",
    )
    print("[self-test] mode=%s" % res["mode"])
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
        print("用法：python3 llm_client.py [--self-test | --self-test-real]")
        return 1
    if argv[0] == "--self-test":
        return self_test(real=False)
    if argv[0] == "--self-test-real":
        return self_test(real=True)
    print("未知参数：%s" % " ".join(argv), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())

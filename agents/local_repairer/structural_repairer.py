# -*- coding: utf-8 -*-
"""
StructuralRepairer：结构性修复模式（面向状态迁移/握手类缺陷）
============================================================
背景：当前 LocalRepairer 以"最小 unified diff"约束生成修复，对状态机
拆分、增加中间态、改写转移条件等结构性改动天然压制。本模块为状态迁移/
握手/协议类缺陷提供结构性修复 prompt，显式允许新增状态、辅助寄存器、
重写转移条件。

用法：
    from agents.local_repairer.structural_repairer import apply_structural_mode
    prompt = apply_structural_mode(prompt, meta.get("error_type", ""))
"""

STRUCTURAL_TYPES = ("状态跳转", "状态迁移", "握手", "协议", "state_trans", "handshake")


def is_structural(error_type):
    if not error_type:
        return False
    return any(t in error_type for t in STRUCTURAL_TYPES)


def structural_prompt_suffix(error_type):
    return (
        "\n【结构性修复模式（由缺陷类型 %s 触发）】\n"
        "本缺陷属于状态迁移/握手类，行级最小补丁可能不足。允许并鼓励：\n"
        "  1. 新增中间状态或拆分现有状态（例如 S2 → S2_WAIT → S3）；\n"
        "  2. 增加辅助寄存器/计数器（例如握手超时计数、协议等待延时）；\n"
        "  3. 重写状态转移条件或触发沿（对齐时序要求）。\n"
        "约束：\n"
        "  - 不得修改断言集、模块端口与接口信号语义；\n"
        "  - 新增信号必须声明并正确复位；\n"
        "  - diff 仍须合法可应用（unified diff 格式，可含多 hunk）；\n"
        "  - 若行级修复已充分，优先行级修复（不过度设计）。\n"
        % (error_type or "?")
    )


def apply_structural_mode(prompt, error_type):
    if is_structural(error_type):
        return prompt + structural_prompt_suffix(error_type)
    return prompt


if __name__ == "__main__":
    for t in ["状态跳转", "握手", "边界回绕", "复位"]:
        print("%-8s -> structural=%s" % (t, is_structural(t)))
    print()
    print(apply_structural_mode("[原 prompt]", "状态跳转")[:400])
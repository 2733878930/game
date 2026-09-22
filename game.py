# -*- coding: utf-8 -*-
"""
================================================================================
 free_text_game.py —— 自由行动文字游戏框架（完整融合版）
================================================================================

【本版新增】
  1. 捏人系统：进入游戏前自定义名字、性别、年龄、身份、外观
  2. 多角色可选：自选互动对象，角色有性别和性向
  3. 暗号系统：输入特定暗号解锁隐藏模式（含隐藏彩蛋）

【设计来源】
  融合了「数据驱动」和「自由行动」两种思路：
  - 数据驱动：场景、对话、接触选项全用 dict
  - 自由行动：玩家输入自然语言关键词，包含匹配并判定结果

【核心特性】
  - 捏人系统：自定义角色身份
  - 自由输入：输入"我想牵她的手"也能匹配到"牵手"
  - 动作注册表：新增互动类型只需注册一个处理函数
  - 玩家属性：体力/心情/名声，行动有代价
  - 回合制：每动作消耗时间，NPC 状态随时间变化
  - 随机结果：同一动作有结果池，每次略有不同
  - 暗号系统：隐藏模式 + 彩蛋
  - 存档/读档：状态序列化成 JSON

【运行】
  python free_text_game.py
================================================================================
"""

import json
import os
import random
import time
from dataclasses import dataclass, field, asdict
from typing import Callable, Dict, List, Optional, Any


# ==============================================================================
# 第一部分：玩家与角色数据模型
# ==============================================================================

@dataclass
class Player:
    """
    玩家状态。包含捏人信息 + 游戏属性。
    捏人信息（name/gender/age/identity/appearance）在开局时设置，
    游戏属性（stamina/mood/fame/money）在游戏过程中变化。
    """
    # ---- 捏人信息 ----
    name: str = "玩家"
    gender: str = "未设定"        # 男 / 女 / 其他
    age: int = 18
    identity: str = "学生"        # 学生 / 上班族 / 自由职业 等
    appearance: str = "普通"      # 外观描述
    pronouns: str = "TA"          # 代称，影响文本渲染

    # ---- 游戏属性 ----
    stamina: int = 100
    mood: int = 70
    fame: int = 50
    money: int = 100
    traits: Dict[str, int] = field(default_factory=dict)

    def change(self, key: str, delta: int):
        """通用属性修改，带上下限。"""
        if key in ("stamina", "mood", "fame"):
            setattr(self, key, max(0, min(100, getattr(self, key) + delta)))
        elif key == "money":
            self.money = max(0, self.money + delta)
        else:
            self.traits[key] = max(0, self.traits.get(key, 0) + delta)


@dataclass
class Character:
    """
    角色状态。
    - gender：角色性别
    - preference：角色性向（"男"/"女"/"不限"），影响亲密互动的接受度
    - affection/trust：好感与信任，分开计算
    """
    name: str
    gender: str = "女"
    preference: str = "不限"      # 喜欢的玩家性别
    age: int = 18
    identity: str = "学生"
    appearance: str = "普通"

    affection: int = 0
    trust: int = 0
    mood: str = "平静"
    flags: Dict[str, bool] = field(default_factory=dict)

    def change_affection(self, delta: int):
        self.affection = max(0, min(100, self.affection + delta))

    def change_trust(self, delta: int):
        self.trust = max(0, min(100, self.trust + delta))

    def set_flag(self, key: str, val: bool = True):
        self.flags[key] = val

    def has_flag(self, key: str) -> bool:
        return self.flags.get(key, False)

    def accepts(self, player_gender: str) -> bool:
        """
        判断角色是否接受该性别的玩家做亲密互动。
        preference 为"不限"则都接受。
        """
        return self.preference == "不限" or self.preference == player_gender


# ==============================================================================
# 第二部分：游戏状态
# ==============================================================================

class GameState:
    """全局游戏状态。"""

    def __init__(self, start_scene: str):
        self.player = Player()
        self.characters: Dict[str, Character] = {}
        self.current_scene = start_scene
        self.flags: set = set()
        self.inventory: List[str] = []
        self.turn: int = 0
        self.ending: Optional[str] = None

    def get_character(self, name: str) -> Character:
        if name not in self.characters:
            self.characters[name] = Character(name=name)
        return self.characters[name]

    def add_flag(self, flag: str):
        self.flags.add(flag)

    def has_flag(self, flag: str) -> bool:
        return flag in self.flags


# ==============================================================================
# 第三部分：文本界面
# ==============================================================================

class TextUI:
    """负责所有输入输出。"""

    SLOW = True
    DELAY = 0.015

    @staticmethod
    def slow_print(text: str):
        if not TextUI.SLOW:
            print(text)
            return
        for ch in text:
            print(ch, end="", flush=True)
            time.sleep(TextUI.DELAY)
        print()

    @staticmethod
    def narrate(text: str):
        print()
        TextUI.slow_print(f"【{text}】")

    @staticmethod
    def say(speaker: str, text: str, mood: str = ""):
        mood_str = f"（{mood}）" if mood else ""
        print()
        TextUI.slow_print(f"{speaker}{mood_str}：「{text}」")

    @staticmethod
    def action(text: str):
        print()
        TextUI.slow_print(f"*{text}*")

    @staticmethod
    def divider():
        print("\n" + "─" * 50)


# ==============================================================================
# 第四部分：输入解析
# ==============================================================================

def parse_input(text: str) -> dict:
    """把玩家输入解析成指令字典。"""
    text = text.strip()
    if not text:
        return {"type": "invalid"}

    low = text.lower()
    if low in ("q", "quit", "exit", "退出", "结束"):
        return {"type": "quit"}
    if low in ("h", "help", "帮助", "?"):
        return {"type": "help"}
    if low in ("s", "status", "状态"):
        return {"type": "status"}
    if low in ("save", "存档"):
        return {"type": "save"}
    if low in ("load", "读档"):
        return {"type": "load"}

    if text.isdigit():
        return {"type": "choice", "index": int(text) - 1}

    return {"type": "text", "keyword": text}


# ==============================================================================
# 第五部分：动作处理器注册表
# ==============================================================================

ACTIONS: Dict[str, Callable] = {}


def register_action(name: str):
    def wrapper(func):
        ACTIONS[name] = func
        return func
    return wrapper


def _resolve_target(target, state: GameState) -> Optional[str]:
    if callable(target):
        return target(state)
    return target


def _random_pick(options: List[str]) -> str:
    return random.choice(options) if options else ""


def _show_relation(name: str, state: GameState) -> str:
    c = state.get_character(name)
    return f"（{name} 好感 {c.affection} / 信任 {c.trust} / 情绪 {c.mood}）"


@register_action("talk")
def action_talk(choice: dict, state: GameState, ctx: dict) -> str:
    """对话动作。"""
    name = choice.get("character", "对方")
    char = state.get_character(name)

    lines = []

    cond = choice.get("condition")
    if cond:
        flag = cond.get("flag")
        if state.has_flag(flag):
            lines.append(cond.get("yes", ""))
        else:
            lines.append(cond.get("no", ""))

    for line in choice.get("lines", []):
        lines.append(line)

    pool = choice.get("pool", [])
    if pool:
        lines.append(_random_pick(pool))

    text = "\n".join(f"{name}：「{l}」" for l in lines if l)

    char.change_affection(choice.get("affection", 2))
    char.change_trust(choice.get("trust_delta", 1))
    char.mood = choice.get("mood_ok", "平静")

    state.add_flag("chatted")
    if choice.get("flag"):
        state.add_flag(choice["flag"])

    text += "\n" + _show_relation(name, state)
    return text


@register_action("touch")
def action_touch(choice: dict, state: GameState, ctx: dict) -> str:
    """
    肢体接触。新增：性别偏好检查。
    如果角色性向不接受玩家性别，亲密接触会被拒绝。
    """
    name = choice.get("character")
    char = state.get_character(name)
    player = state.player

    # ---- 性向检查 ----
    if choice.get("intimate", False) and not char.accepts(player.gender):
        char.change_affection(choice.get("affection_on_fail", -3))
        char.mood = "疏远"
        return (f"*{name}轻轻避开了你的动作*\n"
                f"（{name}似乎对你这种性别的亲密接触不太自在）\n"
                + _show_relation(name, state))

    trust_req = choice.get("trust_req", 0)

    # ---- 信任度不足 ----
    if char.trust < trust_req:
        char.change_affection(choice.get("affection_on_fail", -3))
        char.mood = choice.get("mood_bad", "警惕")
        desc = choice.get("fail_text", f"{name}往后缩了一下，明显不太舒服。")
        return (f"*{desc}*\n"
                f"（信任度不足：{char.trust}/{trust_req}，接触被拒绝）\n"
                + _show_relation(name, state))

    # ---- 成功 ----
    char.change_affection(choice.get("affection", 0))
    char.change_trust(choice.get("trust_delta", 0))
    char.mood = choice.get("mood_ok", "开心")

    desc = _random_pick(choice.get("pool", [])) or choice.get("touch", "轻轻碰了一下")
    feedback = choice.get("feedback", "对方的神情缓和了一些。")

    if choice.get("flag"):
        char.set_flag(choice["flag"])

    return (f"*{desc}*\n{feedback}\n" + _show_relation(name, state))


@register_action("give_item")
def action_give_item(choice: dict, state: GameState, ctx: dict) -> str:
    """赠送道具。"""
    item = choice.get("item")
    name = choice.get("character", "对方")
    if not item:
        return "（未配置道具）"

    flag = f"gave_{item}"
    if state.has_flag(flag):
        return f"你已经送过{item}了，{name}摆摆手说不用了。"

    state.add_flag(flag)
    char = state.get_character(name)
    char.change_affection(choice.get("affection", 5))
    char.change_trust(choice.get("trust_delta", 2))
    char.mood = choice.get("mood_ok", "开心")

    return (choice.get("text", f"你把{item}送给了{name}。") + "\n"
            + _show_relation(name, state))


@register_action("free_talk")
def action_free_talk(choice: dict, state: GameState, ctx: dict) -> str:
    """自由交谈兜底。"""
    name = choice.get("character", "对方")
    char = state.get_character(name)
    char.change_affection(1)
    pool = [
        f"你和{name}随意聊了几句，气氛还算轻松。",
        f"{name}嗯了一声，似乎没太在意你说的话。",
        f"你说了几句，{name}安静地听着。",
    ]
    return _random_pick(pool) + "\n" + _show_relation(name, state)


@register_action("move")
def action_move(choice: dict, state: GameState, ctx: dict) -> str:
    target = _resolve_target(choice.get("to"), state)
    if target:
        state.current_scene = target
    return choice.get("text", "你走了过去。")


@register_action("ending")
def action_ending(choice: dict, state: GameState, ctx: dict) -> str:
    ending = choice.get("ending", "普通结局")
    state.ending = ending
    return choice.get("text", f"【结局达成：{ending}】")


@register_action("rest")
def action_rest(choice: dict, state: GameState, ctx: dict) -> str:
    state.player.change("stamina", choice.get("stamina", 30))
    state.player.change("mood", choice.get("mood", 5))
    return (choice.get("text", "你闭上眼睛休息了一会儿，感觉好多了。") + "\n"
            f"（体力 {state.player.stamina} / 心情 {state.player.mood}）")


# ==============================================================================
# 第六部分：暗号系统（隐藏模式）
# ==============================================================================

SECRET_CODES: Dict[str, dict] = {}


def register_secret(code: str, desc: str = "", hidden: bool = True):
    """装饰器：注册一个暗号。"""
    def wrapper(func):
        SECRET_CODES[code] = {"func": func, "desc": desc, "hidden": hidden}
        return func
    return wrapper


def try_secret(text: str, state: GameState, engine) -> Optional[str]:
    """
    尝试匹配暗号。
    支持精确匹配和带参数前缀匹配（如 whale_skip 5）。
    """
    raw = text.strip()
    low = raw.lower()

    # 精确匹配
    for code, info in SECRET_CODES.items():
        if low == code.lower():
            return info["func"](state, engine, [])

    # 前缀匹配（带参数）
    parts = raw.split()
    if len(parts) >= 2:
        code = parts[0].lower()
        args = parts[1:]
        for c, info in SECRET_CODES.items():
            if code == c.lower():
                return info["func"](state, engine, args)

    return None


@register_secret("whale_dev", "开启开发者模式", hidden=False)
def secret_dev_mode(state: GameState, engine, args) -> str:
    engine.dev_mode = not getattr(engine, "dev_mode", False)
    status = "开启" if engine.dev_mode else "关闭"
    return f"🐋 开发者模式已{status}。"


@register_secret("whale_inf", "无限体力", hidden=False)
def secret_infinite(state: GameState, engine, args) -> str:
    state.player.stamina = 100
    state.add_flag("__infinite_stamina__")
    return "🐋 无限体力已解锁。你感觉浑身充满力量。"


@register_secret("whale_love", "所有角色好感信任拉满", hidden=False)
def secret_love(state: GameState, engine, args) -> str:
    for c in state.characters.values():
        c.affection = 100
        c.trust = 100
        c.mood = "开心"
    return "🐋 所有角色的好感与信任已拉满。世界对你温柔以待。"


@register_secret("whale_debug", "显示调试信息", hidden=False)
def secret_debug(state: GameState, engine, args) -> str:
    lines = ["🐋 【调试面板】"]
    lines.append(f"  场景：{state.current_scene}  回合：{state.turn}")
    lines.append(f"  玩家：{state.player.name}（{state.player.gender}/{state.player.age}岁/"
                 f"{state.player.identity}）")
    lines.append(f"  属性：体力 {state.player.stamina} / 心情 {state.player.mood} / "
                 f"名声 {state.player.fame} / 钱 {state.player.money}")
    lines.append(f"  标记：{sorted(state.flags)}")
    for name, c in state.characters.items():
        lines.append(f"  角色 {name}：{c.gender}/{c.age}岁/{c.identity} "
                     f"好感 {c.affection} / 信任 {c.trust} / 情绪 {c.mood}")
    return "\n".join(lines)


@register_secret("whale_skip", "跳过 N 回合：whale_skip 5", hidden=False)
def secret_skip(state: GameState, engine, args) -> str:
    try:
        n = int(args[0]) if args else 1
    except ValueError:
        return "🐋 参数不对，用法：whale_skip 5"
    for _ in range(n):
        engine.tick()
    return f"🐋 已跳过 {n} 回合。当前回合：{state.turn}"


@register_secret("whale_secret", "", hidden=True)
def secret_easter_egg(state: GameState, engine, args) -> str:
    """隐藏彩蛋。"""
    lines = [
        "🐋 空气中浮现出一行字：",
        "「你找到了鲸鱼娘的暗号。」",
    ]
    if state.characters:
        target = list(state.characters.values())[0]
        target.set_flag("知道秘密")
        target.change_affection(20)
        target.change_trust(20)
        target.mood = "惊讶"
        lines.append(f"{target.name}抬起头，眼睛亮了一下：")
        lines.append(f"{target.name}：「刚才……你听到了吗？好像有人说话。」")
        lines.append(f"（{target.name} 好感 +20，信任 +20，获得标记：知道秘密）")
    state.add_flag("__secret_found__")
    return "\n".join(lines)


@register_secret("whale_help", "显示所有暗号", hidden=True)
def secret_whale_help(state: GameState, engine, args) -> str:
    """列出所有暗号（包括隐藏的）。"""
    lines = ["🐋 【所有暗号】"]
    for code, info in SECRET_CODES.items():
        hidden_tag = "（隐藏）" if info["hidden"] else ""
        lines.append(f"  {code}  —— {info['desc']}{hidden_tag}")
    return "\n".join(lines)


@register_secret("whale_reset", "重置角色关系", hidden=True)
def secret_reset(state: GameState, engine, args) -> str:
    """把所有角色关系重置为初始值。"""
    for c in state.characters.values():
        c.affection = 0
        c.trust = 0
        c.mood = "平静"
        c.flags.clear()
    return "🐋 所有角色关系已重置。"


# ==============================================================================
# 第七部分：捏人系统（进入游戏前自定义角色）
# ==============================================================================

class CharacterCreator:
    """
    捏人系统。
    进入游戏前，让玩家自定义：
      - 名字
      - 性别（男/女/其他）
      - 年龄
      - 身份（学生/上班族/自由职业/其他）
      - 外观描述
    同时让玩家选择本轮要互动的对象（可选多个角色）。
    """

    # 可选身份
    IDENTITIES = ["学生", "上班族", "自由职业", "艺术家", "旅行者"]

    # 可选性别
    GENDERS = ["男", "女", "其他"]

    @staticmethod
    def create_player() -> Player:
        """引导玩家创建自己的角色。"""
        print("\n" + "=" * 50)
        print("  🐋 角色创建")
        print("=" * 50)
        print("在开始之前，先来设定一下你自己吧。")
        print("（直接回车使用默认值）\n")

        # ---- 名字 ----
        name = input("你的名字：").strip() or "无名"

        # ---- 性别 ----
        print("\n性别选项：")
        for i, g in enumerate(CharacterCreator.GENDERS, 1):
            print(f"  {i}. {g}")
        raw = input("选择性别（编号或直接输入）：").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(CharacterCreator.GENDERS):
            gender = CharacterCreator.GENDERS[int(raw) - 1]
        elif raw:
            gender = raw
        else:
            gender = "其他"

        # ---- 年龄 ----
        raw = input("\n年龄（默认 18）：").strip()
        try:
            age = int(raw) if raw else 18
        except ValueError:
            age = 18

        # ---- 身份 ----
        print("\n身份选项：")
        for i, ident in enumerate(CharacterCreator.IDENTITIES, 1):
            print(f"  {i}. {ident}")
        raw = input("选择身份（编号或直接输入）：").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(CharacterCreator.IDENTITIES):
            identity = CharacterCreator.IDENTITIES[int(raw) - 1]
        elif raw:
            identity = raw
        else:
            identity = "学生"

        # ---- 外观 ----
        appearance = input("\n外观描述（如：黑发、戴眼镜，可留空）：").strip() or "普通"

        # ---- 代称 ----
        # 根据性别自动选代称，也可以手动覆盖
        default_pronoun = {"男": "他", "女": "她", "其他": "TA"}.get(gender, "TA")
        raw = input(f"\n代称（默认「{default_pronoun}」）：").strip()
        pronouns = raw or default_pronoun

        # ---- 汇总 ----
        player = Player(
            name=name,
            gender=gender,
            age=age,
            identity=identity,
            appearance=appearance,
            pronouns=pronouns,
        )

        print("\n" + "=" * 50)
        print("  你的角色")
        print("=" * 50)
        print(f"  名字：{player.name}")
        print(f"  性别：{player.gender}")
        print(f"  年龄：{player.age}")
        print(f"  身份：{player.identity}")
        print(f"  外观：{player.appearance}")
        print(f"  代称：{player.pronouns}")
        print("=" * 50)

        return player

    @staticmethod
    def choose_companion() -> Character:
        """
        让玩家选择本轮要互动的角色。
        这里提供几个预设角色，各有性别、年龄、身份、性向。
        """
        print("\n" + "=" * 50)
        print("  🐋 选择互动对象")
        print("=" * 50)

        presets = [
            Character(
                name="小鲸", gender="女", preference="不限",
                age=18, identity="学生",
                appearance="长发，安静，喜欢在公园看书",
            ),
            Character(
                name="阿澈", gender="男", preference="不限",
                age=20, identity="大学生",
                appearance="短发，爱笑，总背着吉他",
            ),
            Character(
                name="凛", gender="其他", preference="不限",
                age=22, identity="艺术家",
                appearance="银色短发，中性气质，画速写",
            ),
            Character(
                name="老周", gender="男", preference="女",
                age=35, identity="咖啡店老板",
                appearance="成熟稳重，话不多",
            ),
            Character(
                name="小雅", gender="女", preference="男",
                age=19, identity="学生",
                appearance="爱穿裙子，喜欢甜食",
            ),
        ]

        for i, c in enumerate(presets, 1):
            print(f"  {i}. {c.name}（{c.gender}，{c.age}岁，{c.identity}）")
            print(f"      {c.appearance}")

        raw = input("\n选择互动对象（编号，默认 1）：").strip()
        idx = int(raw) - 1 if raw.isdigit() and 1 <= int(raw) <= len(presets) else 0

        chosen = presets[idx]
        print(f"\n你选择了：{chosen.name}")
        return chosen


# ==============================================================================
# 第八部分：场景渲染
# ==============================================================================

def render_scene(scene: dict, state: GameState) -> str:
    """渲染场景。"""
    lines = []
    lines.append(f"【{scene.get('title', '未知地点')}】")
    lines.append(scene.get("desc", ""))

    present = scene.get("characters", [])
    if present:
        lines.append("")
        lines.append("在场：" + "、".join(present))

    p = state.player
    lines.append("")
    lines.append(f"（{p.name}：体力 {p.stamina} / 心情 {p.mood} / "
                 f"名声 {p.fame} / 钱 {p.money} / 回合 {state.turn}）")

    choices = scene.get("choices", [])
    if choices:
        lines.append("")
        lines.append("可选动作：")
        for i, c in enumerate(choices, start=1):
            label = c.get("label", "")
            trigger = c.get("trigger", "")
            req = c.get("trust_req")
            suffix = f"（需信任≥{req}）" if req else ""
            lines.append(f"  {i}. {label}  [{trigger}]{suffix}")

    lines.append("")
    lines.append("（输入数字或关键词，也可自由输入你想做的事）")
    return "\n".join(lines)


# ==============================================================================
# 第九部分：游戏引擎
# ==============================================================================

class GameEngine:
    """游戏引擎。"""

    def __init__(self, scenes: dict, start_scene: str):
        self.scenes = scenes
        self.state = GameState(start_scene)
        self.running = True
        self.dev_mode = False

    def find_choice(self, scene: dict, index=None, keyword=None) -> Optional[dict]:
        """匹配选项。"""
        choices = scene.get("choices", [])

        if index is not None:
            if 0 <= index < len(choices):
                return choices[index]
            return None

        if keyword is not None:
            kw = keyword.strip()

            # 精确匹配
            for c in choices:
                if c.get("trigger") == kw:
                    return c

            # 包含匹配
            best = None
            best_len = 0
            for c in choices:
                trigger = c.get("trigger", "")
                label = c.get("label", "")
                for target in (trigger, label):
                    if not target:
                        continue
                    if target in kw or kw in target:
                        if len(target) > best_len:
                            best = c
                            best_len = len(target)
            return best

        return None

    def run_choice(self, choice: dict) -> str:
        action_name = choice.get("action")
        if action_name and action_name in ACTIONS:
            return ACTIONS[action_name](choice, self.state, {})
        if "to" in choice:
            self.state.current_scene = _resolve_target(choice["to"], self.state)
        return choice.get("text", "")

    def tick(self):
        """每回合流逝。"""
        self.state.turn += 1

        # 无限体力标记
        if not self.state.has_flag("__infinite_stamina__"):
            self.state.player.change("stamina", -1)

        for c in self.state.characters.values():
            if c.mood in ("开心", "害羞", "安心") and random.random() < 0.3:
                c.mood = "平静"

        if self.state.player.stamina <= 0:
            TextUI.narrate("你实在太累了，眼前一阵发黑……")
            self.state.player.stamina = 20
            self.state.player.change("mood", -10)

    def save(self, path: str = "save.json"):
        data = {
            "player": asdict(self.state.player),
            "characters": {n: asdict(c) for n, c in self.state.characters.items()},
            "current_scene": self.state.current_scene,
            "flags": list(self.state.flags),
            "inventory": self.state.inventory,
            "turn": self.state.turn,
            "ending": self.state.ending,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"已保存到 {path}")

    def load(self, path: str = "save.json"):
        if not os.path.exists(path):
            print("存档不存在。")
            return
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.state.player = Player(**data["player"])
        self.state.characters = {
            n: Character(**c) for n, c in data["characters"].items()
        }
        self.state.current_scene = data["current_scene"]
        self.state.flags = set(data["flags"])
        self.state.inventory = data["inventory"]
        self.state.turn = data["turn"]
        self.state.ending = data["ending"]
        print(f"已从 {path} 读取存档。")

    # ---------- 主循环 ----------
    def step(self):
        print("=" * 50)
        print("  自由行动文字游戏（完整融合版）")
        print("  输入数字或关键词，也可以直接输入你想做的事")
        print("  命令：h 帮助 / s 状态 / save 存档 / load 读档 / q 退出")
        print("=" * 50)

        while self.running and self.state.ending is None:
            scene = self.scenes.get(self.state.current_scene)
            if scene is None:
                print("[错误] 场景不存在，游戏结束。")
                break

            TextUI.divider()
            print(render_scene(scene, self.state))

            raw = input("\n> ").strip()

            # ---- 暗号拦截 ----
            secret_result = try_secret(raw, self.state, self)
            if secret_result is not None:
                print()
                print(secret_result)
                continue

            cmd = parse_input(raw)

            # ---- 系统命令 ----
            if cmd["type"] == "quit":
                print("你退出了游戏。")
                break
            elif cmd["type"] == "help":
                self._print_help()
                continue
            elif cmd["type"] == "status":
                self._show_status()
                continue
            elif cmd["type"] == "save":
                self.save()
                continue
            elif cmd["type"] == "load":
                self.load()
                continue
            elif cmd["type"] == "invalid":
                print("（输入为空，请重新输入）")
                continue

            # ---- 匹配选项 ----
            if cmd["type"] == "choice":
                choice = self.find_choice(scene, index=cmd["index"])
                if choice is None:
                    print("（没有这个编号的选项）")
                    continue
            else:
                choice = self.find_choice(scene, keyword=cmd["keyword"])
                if choice is None:
                    present = scene.get("characters", [])
                    if present:
                        choice = {"action": "free_talk", "character": present[0]}
                    else:
                        print(f"（这里似乎做不了「{cmd['keyword']}」）")
                        continue

            # ---- 执行 ----
            result = self.run_choice(choice)
            if result:
                print()
                print(result)

            # ---- 开发者模式附加信息 ----
            if self.dev_mode:
                print(f"\n[dev] 场景={self.state.current_scene} 回合={self.state.turn} "
                      f"体力={self.state.player.stamina}")

            # ---- 回合流逝 ----
            self.tick()

        if self.state.ending:
            print("\n" + "=" * 50)
            print(f"游戏结束：{self.state.ending}")
            print("=" * 50)

    def _print_help(self):
        print("输入数字选选项，或输入触发词。也可以自由输入想做的事。")
        print("命令：s 状态 / save 存档 / load 读档 / q 退出")
        print("\n【可用暗号】")
        for code, info in SECRET_CODES.items():
            if not info["hidden"]:
                print(f"  {code}  —— {info['desc']}")

    def _show_status(self):
        s = self.state
        p = s.player
        print("\n【当前状态】")
        print(f"  角色：{p.name}（{p.gender}/{p.age}岁/{p.identity}）")
        print(f"  代称：{p.pronouns}   外观：{p.appearance}")
        print(f"  场景：{s.current_scene}   回合：{s.turn}")
        print(f"  体力 {p.stamina} / 心情 {p.mood} / 名声 {p.fame} / 钱 {p.money}")
        if s.characters:
            print("  角色关系：")
            for name, c in s.characters.items():
                print(f"    {name}（{c.gender}/{c.age}岁/{c.identity}）："
                      f"好感 {c.affection} / 信任 {c.trust} / 情绪 {c.mood}")
        if s.flags:
            print(f"  已触发事件：{', '.join(sorted(s.flags))}")


# ==============================================================================
# 第十部分：示例剧情数据
# ==============================================================================

def build_scenes(companion_name: str) -> dict:
    """
    构造场景。companion_name 是玩家选择的互动对象名字，
    场景里直接用它，让剧情适配不同角色。
    """
    return {
        "park_entrance": {
            "title": "公园入口",
            "desc": f"清晨的阳光透过树叶洒下来。长椅上坐着一个人——{companion_name}。",
            "characters": [],
            "choices": [
                {"label": "走过去打招呼", "trigger": "打招呼",
                 "action": "move", "to": "bench",
                 "text": "你朝长椅走了过去。"},
                {"label": "在远处观察", "trigger": "观察",
                 "action": "move", "to": "observe",
                 "text": "你站在不远处，静静看着。"},
                {"label": "离开公园", "trigger": "离开",
                 "action": "ending", "ending": "平淡的一天",
                 "text": "你转身离开，今天没有发生什么特别的事。"},
                {"label": "休息一下", "trigger": "休息", "action": "rest"},
            ],
        },

        "bench": {
            "title": "长椅旁",
            "desc": f"{companion_name}抬起头，看到你走近，微微一愣，随后露出礼貌的微笑。",
            "characters": [companion_name],
            "choices": [
                {
                    "label": "和TA聊天",
                    "trigger": "聊天",
                    "action": "talk",
                    "character": companion_name,
                    "condition": {
                        "flag": "chatted",
                        "yes": "又见面了，你也喜欢清晨的公园吗？",
                        "no": "第一次见面就聊天，你不怕我是坏人吗？",
                    },
                    "lines": ["这里安静，适合待着。"],
                    "pool": [
                        "说话的时候，TA的眼睛一直看着远处。",
                        "风吹过来，TA的头发轻轻晃了一下。",
                    ],
                    "affection": 2,
                    "trust_delta": 1,
                },
                {
                    "label": "递给TA一颗糖果",
                    "trigger": "糖果",
                    "action": "give_item",
                    "character": companion_name,
                    "item": "糖果",
                    "affection": 5,
                    "trust_delta": 3,
                    "text": f"{companion_name}犹豫了一下，接过糖果，小声说了句谢谢。",
                },
                {
                    "label": "伸手想和TA握手",
                    "trigger": "握手",
                    "action": "touch",
                    "character": companion_name,
                    "trust_req": 5,
                    "trust_delta": 3,
                    "affection": 3,
                    "mood_ok": "害羞",
                    "mood_bad": "警惕",
                    "touch": "你微笑着向TA伸出手。",
                    "pool": [
                        "TA迟疑片刻，轻轻握了一下你的手，指尖有点凉。",
                        "TA的手在你掌心里停了半秒，又快速收回。",
                    ],
                    "fail_text": f"{companion_name}往后缩了一下，没有伸手。",
                    "flag": "已握手",
                },
                {
                    "label": "轻轻拍拍TA的肩",
                    "trigger": "拍肩",
                    "action": "touch",
                    "character": companion_name,
                    "trust_req": 15,
                    "trust_delta": 2,
                    "affection": 6,
                    "mood_ok": "安心",
                    "mood_bad": "抗拒",
                    "touch": "你轻轻拍了拍TA的肩膀。",
                    "feedback": "TA愣了一瞬，随后对你点了点头。",
                    "fail_text": "TA下意识地躲开了你的手。",
                    "flag": "已拍肩",
                },
                {
                    "label": "拥抱TA",
                    "trigger": "拥抱",
                    "action": "touch",
                    "character": companion_name,
                    "trust_req": 40,
                    "trust_delta": 5,
                    "affection": 12,
                    "mood_ok": "安心",
                    "mood_bad": "生气",
                    "touch": "你张开手臂，轻轻抱住了TA。",
                    "feedback": "TA僵了一下，然后把头靠在你肩上。",
                    "fail_text": "TA用力推开了你，脸上写满抗拒。",
                    "affection_on_fail": -8,
                    "flag": "已拥抱",
                    "intimate": True,   # 标记为亲密互动，会检查性向
                },
                {
                    "label": "问TA的名字",
                    "trigger": "名字",
                    "action": "talk",
                    "character": companion_name,
                    "lines": [f"我叫{companion_name}。你呢？"],
                    "pool": ["TA说完就低下头，好像有点不好意思。"],
                    "affection": 2,
                    "trust_delta": 2,
                    "flag": "知道名字",
                },
                {"label": "休息一下", "trigger": "休息", "action": "rest"},
                {"label": "转身离开", "trigger": "离开",
                 "action": "move", "to": "park_entrance",
                 "text": "你道别后走回公园入口。"},
            ],
        },

        "observe": {
            "title": "远处的观察点",
            "desc": f"你站在一棵老槐树下，远远看着{companion_name}。TA偶尔停下来，对着天空发呆。",
            "characters": [],
            "choices": [
                {"label": "最终还是走过去", "trigger": "走过去",
                 "action": "move", "to": "bench",
                 "text": "你深吸一口气，朝长椅走去。"},
                {"label": "看完就默默离开", "trigger": "离开",
                 "action": "ending", "ending": "擦肩而过的清晨",
                 "text": "你看了一会，转身离开。有些相遇，可能本来就不需要开始。"},
            ],
        },
    }


# ==============================================================================
# 第十一部分：程序入口
# ==============================================================================

def main():
    """程序入口：先捏人，再选对象，最后开始游戏。"""
    # ---- 1. 捏人 ----
    player = CharacterCreator.create_player()

    # ---- 2. 选互动对象 ----
    companion = CharacterCreator.choose_companion()

    # ---- 3. 构建引擎 ----
    scenes = build_scenes(companion.name)
    engine = GameEngine(scenes, "park_entrance")

    # 把捏好的玩家和选好的角色放进状态
    engine.state.player = player
    engine.state.characters[companion.name] = companion

    # ---- 4. 开场白 ----
    print("\n" + "=" * 50)
    TextUI.narrate(
        f"{player.name}，{player.age}岁，{player.identity}。"
        f"今天清晨，你来到了公园。"
    )
    TextUI.narrate(f"长椅上坐着{companion.name}。")

    # ---- 5. 开始游戏 ----
    engine.step()


if __name__ == "__main__":
    main()
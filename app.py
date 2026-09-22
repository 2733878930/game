# -*- coding: utf-8 -*-
"""
Streamlit 网页版入口。
把游戏引擎包装成网页界面，不用写 HTML。
"""
import streamlit as st

from game import GameEngine, build_scenes, CharacterCreator
from game import try_secret, parse_input, render_scene


# ============================================================
# 页面设置
# ============================================================
st.set_page_config(
    page_title="文字互动游戏",
    page_icon="🐋",
    layout="centered",
)

# 自定义样式（让界面好看一点）
st.markdown("""
<style>
    .stApp { background: #1a1a2e; color: #e0e0e0; }
    .dialogue { color: #e0e0e0; line-height: 1.8; }
    .player { color: #7fdbff; }
    .ending { color: #ffd700; font-weight: bold; }
</style>
""", unsafe_allow_html=True)


# ============================================================
# 会话状态初始化
# ============================================================
# Streamlit 每次交互都会重跑整个脚本，所以游戏状态必须存在 session_state 里
if "engine" not in st.session_state:
    st.session_state.engine = None
if "history" not in st.session_state:
    st.session_state.history = []   # 显示在页面上的历史文本
if "phase" not in st.session_state:
    st.session_state.phase = "create"   # create / choose / play


# ============================================================
# 阶段一：捏人
# ============================================================
def phase_create():
    st.title("🐋 角色创建")
    st.write("在开始之前，先来设定一下你自己吧。")

    with st.form("create_form"):
        name = st.text_input("名字", value="无名")
        gender = st.selectbox("性别", ["男", "女", "其他"])
        age = st.number_input("年龄", min_value=1, max_value=120, value=18)
        identity = st.selectbox(
            "身份",
            ["学生", "上班族", "自由职业", "艺术家", "旅行者"]
        )
        appearance = st.text_input("外观描述", value="普通")
        pronoun_default = {"男": "他", "女": "她", "其他": "TA"}[gender]
        pronouns = st.text_input("代称", value=pronoun_default)

        submitted = st.form_submit_button("下一步：选择互动对象")

    if submitted:
        # 把玩家信息暂存
        st.session_state.player_info = {
            "name": name,
            "gender": gender,
            "age": age,
            "identity": identity,
            "appearance": appearance,
            "pronouns": pronouns,
        }
        st.session_state.phase = "choose"
        st.rerun()


# ============================================================
# 阶段二：选择互动对象
# ============================================================
def phase_choose():
    st.title("🐋 选择互动对象")

    presets = [
        {"name": "小鲸", "gender": "女", "age": 18, "identity": "学生",
         "appearance": "长发，安静，喜欢在公园看书"},
        {"name": "阿澈", "gender": "男", "age": 20, "identity": "大学生",
         "appearance": "短发，爱笑，总背着吉他"},
        {"name": "凛", "gender": "其他", "age": 22, "identity": "艺术家",
         "appearance": "银色短发，中性气质"},
        {"name": "老周", "gender": "男", "age": 35, "identity": "咖啡店老板",
         "appearance": "成熟稳重，话不多"},
        {"name": "小雅", "gender": "女", "age": 19, "identity": "学生",
         "appearance": "爱穿裙子，喜欢甜食"},
    ]

    labels = [f"{c['name']}（{c['gender']}，{c['age']}岁，{c['identity']}）" for c in presets]
    idx = st.radio("选择你想互动的对象：", range(len(labels)),
                   format_func=lambda i: labels[i])

    chosen = presets[idx]
    st.caption(chosen["appearance"])

    if st.button("开始游戏"):
        # 构建引擎
        scenes = build_scenes(chosen["name"])
        engine = GameEngine(scenes, "park_entrance")

        # 设置玩家
        info = st.session_state.player_info
        from game import Player, Character
        engine.state.player = Player(**info)

        # 设置角色
        char = Character(
            name=chosen["name"],
            gender=chosen["gender"],
            age=chosen["age"],
            identity=chosen["identity"],
            appearance=chosen["appearance"],
        )
        engine.state.characters[chosen["name"]] = char

        st.session_state.engine = engine
        st.session_state.history = [
            f"【{info['name']}，{info['age']}岁，{info['identity']}。今天清晨，你来到了公园。】",
            f"【长椅上坐着{chosen['name']}。】",
            "",
            render_scene(engine.scenes["park_entrance"], engine.state),
        ]
        st.session_state.phase = "play"
        st.rerun()


# ============================================================
# 阶段三：游戏主界面
# ============================================================
def phase_play():
    engine = st.session_state.engine

    # ---- 左侧：状态栏 ----
    # 用两列布局：左窄右宽
    col_left, col_right = st.columns([1, 3])

    with col_left:
        st.subheader("状态")
        p = engine.state.player
        st.write(f"**{p.name}**")
        st.write(f"{p.gender} / {p.age}岁 / {p.identity}")
        st.write(f"体力：{p.stamina}")
        st.progress(p.stamina / 100)
        st.write(f"心情：{p.mood}")
        st.progress(p.mood / 100)
        st.write(f"名声：{p.fame}")
        st.write(f"钱：{p.money}")
        st.write(f"回合：{engine.state.turn}")

        st.divider()
        st.write("**角色关系**")
        for name, c in engine.state.characters.items():
            st.write(f"{name}")
            st.write(f"好感：{c.affection}")
            st.progress(c.affection / 100)
            st.write(f"信任：{c.trust}")
            st.progress(c.trust / 100)
            st.write(f"情绪：{c.mood}")

        if st.button("重新开始"):
            st.session_state.clear()
            st.rerun()

    # ---- 右侧：剧情 + 输入 ----
    with col_right:
        st.subheader("剧情")

        # 显示历史
        for line in st.session_state.history:
            st.markdown(line)

        # ---- 结局检查 ----
        if engine.state.ending:
            st.success(f"游戏结束：{engine.state.ending}")
            return

        # ---- 输入区 ----
        st.divider()

        # 快捷按钮：当前场景的选项
        scene = engine.scenes.get(engine.state.current_scene, {})
        choices = scene.get("choices", [])
        if choices:
            st.write("**可选动作**")
            cols = st.columns(min(len(choices), 4))
            for i, c in enumerate(choices):
                label = c.get("label", "")
                with cols[i % 4]:
                    if st.button(label, key=f"btn_{i}"):
                        do_step(c.get("trigger", ""))

        # 自由输入框
        with st.form("input_form", clear_on_submit=True):
            raw = st.text_input("或者直接输入你想做的事：", placeholder="比如：握手、聊天、whale_secret")
            submitted = st.form_submit_button("发送")
        if submitted and raw:
            do_step(raw)


def do_step(raw: str):
    """执行一步游戏，把结果追加到历史。"""
    engine = st.session_state.engine

    st.session_state.history.append(f"<span class='player'>&gt; {raw}</span>")

    # 暗号拦截
    secret_result = try_secret(raw, engine.state, engine)
    if secret_result is not None:
        st.session_state.history.append(secret_result)
        st.rerun()
        return

    # 正常解析
    cmd = parse_input(raw)

    if cmd["type"] == "quit":
        st.session_state.history.append("你退出了游戏。")
        st.rerun()
        return

    if cmd["type"] == "help":
        lines = ["输入数字选选项，或输入触发词。也可以自由输入想做的事。",
                 "命令：s 状态 / save 存档 / load 读档 / q 退出",
                 "", "【可用暗号】"]
        from game import SECRET_CODES
        for code, info in SECRET_CODES.items():
            if not info["hidden"]:
                lines.append(f"  {code}  —— {info['desc']}")
        st.session_state.history.append("\n".join(lines))
        st.rerun()
        return

    if cmd["type"] == "status":
        p = engine.state.player
        st.session_state.history.append(
            f"【状态】{p.name} 体力{p.stamina} 心情{p.mood} 名声{p.fame} 钱{p.money}"
        )
        st.rerun()
        return

    if cmd["type"] == "invalid":
        st.rerun()
        return

    # 匹配选项
    scene = engine.scenes.get(engine.state.current_scene, {})
    if cmd["type"] == "choice":
        choice = engine.find_choice(scene, index=cmd["index"])
    else:
        choice = engine.find_choice(scene, keyword=cmd["keyword"])

    if choice is None:
        present = scene.get("characters", [])
        if present:
            choice = {"action": "free_talk", "character": present[0]}
        else:
            st.session_state.history.append(f"（这里似乎做不了「{raw}」）")
            st.rerun()
            return

    # 执行
    result = engine.run_choice(choice)
    if result:
        st.session_state.history.append(result)

    # 回合流逝
    engine.tick()

    # 显示新场景
    new_scene = engine.scenes.get(engine.state.current_scene, {})
    if new_scene:
        st.session_state.history.append("")
        st.session_state.history.append(render_scene(new_scene, engine.state))

    st.rerun()


# ============================================================
# 路由：根据阶段显示不同界面
# ============================================================
if st.session_state.phase == "create":
    phase_create()
elif st.session_state.phase == "choose":
    phase_choose()
elif st.session_state.phase == "play":
    phase_play()
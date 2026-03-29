from __future__ import annotations
from js import document, window
import random
import asyncio
from pyodide.ffi import create_proxy
from typing import Callable, Optional

event_proxies = []

# ===== DOM =====
cpuA_title = document.getElementById("cpuA-title")
cpuB_title = document.getElementById("cpuB-title")
cpuC_title = document.getElementById("cpuC-title")
you_title = document.getElementById("you-title")
cpuA_cards = document.getElementById("cpuA-cards")
cpuB_cards = document.getElementById("cpuB-cards")
cpuC_cards = document.getElementById("cpuC-cards")

field_img = document.getElementById("field-card")
deck_title = document.getElementById("deck-title")
deck_img = document.getElementById("deck-card")

your_hand = document.getElementById("your-hand")
msg = document.getElementById("msg")
dobon_btn = document.getElementById("dobon-btn")

# ===== cards.js bridge =====
_cards = None

async def ensure_cards():
    global _cards
    if _cards is not None:
        return _cards
    while not hasattr(window, "cards"):
        await asyncio.sleep(0)
    _cards = window.cards
    return _cards

# ===== Game State =====
deck = []       # 山札（残り）
field = None    # 場札（いちばん上1枚）
you = []        # あなたの手札（表で見える）
cpuA = []
cpuB = []
cpuC = []
discard=[]       # 捨て札

TURN_ORDER = ["you", "cpuA", "cpuB", "cpuC"]
current_player_idx = 0
current_player = "you"
dobon_waiting = False
win_stats = {
    "you":  {"win": 0, "total": 0},
    "cpuA": {"win": 0, "total": 0},
    "cpuB": {"win": 0, "total": 0},
    "cpuC": {"win": 0, "total": 0},
}

game_over = False  # 勝敗がついたら True

selected = None  # iPad向け：選択中カードid（1回目タップで選択）

busy = False
cpu_running = False  # CPUが行動中はTrue（あなたの操作を一時的に無効化）
reveal_cpu = None   # "cpuA" / "cpuB" / "cpuC" / None
last_actor = None  # 最後に行動したプレーヤー
last_winner = None   # "you", "cpuA", "cpuB", "cpuC"

def win_rate_str(player: str) -> str:
    w = win_stats[player]["win"]
    t = win_stats[player]["total"]
    rate = (w / t * 100) if t > 0 else 0
    return f"{w}勝/{t}回中（勝率{rate:.1f}%）"

def render_cpu(panel_title_el, panel_cards_el, name: str, cards_list, pid: str):
    n = len(cards_list)
    stats = win_rate_str(pid)
    panel_title_el.innerText = f"{name}（{n}枚） {stats}"

# ---- カード番号→(スート,数字)の割り当て ----
# c1..c52 の並びは「♣→♦→♥→♠（各A..K）」
def card_to_suit_rank(i: int):
    suit_index = (i - 1) // 13  # 0..3
    rank = (i - 1) % 13 + 1     # 1..13
    suits = ["C", "D", "H", "S"]  # ♣ ♦ ♥ ♠ 
    return suits[suit_index], rank

def dobon_possible():
    """
    ルール：手札「すべて」の合計が、場の数字と一致したらドボン可能
    戻り値：(ok, used)
      ok: bool
      used: list（将来拡張用。今は手札全部を返す）
    """
    if field is None or len(you) == 0:
        return False, []

    target = card_to_suit_rank(field)[1]
    total = sum(card_to_suit_rank(cid)[1] for cid in you)

    ok = (total == target)
    used = you[:] if ok else []
    return ok, used


def can_play(card_id: int, field_id: int) -> bool:
    s1, r1 = card_to_suit_rank(card_id)
    s2, r2 = card_to_suit_rank(field_id)
    return (s1 == s2) or (r1 == r2)

def has_playable():
    if field is None:
        return False
    # ★残り1枚は「ドボン宣言」以外では出せない＝playable扱いにしない
    if len(you) == 1:
        return False

    return any(can_play(cid, field) for cid in you)


def set_msg(text: str, ok=False, ng=False):
    msg.className = "ok" if ok else ("ng" if ng else "")
    msg.innerText = text

def clear_node(node):
    while node.firstChild:
        node.removeChild(node.firstChild)

def img_el(src: str, cls: str = ""):
    im = document.createElement("img")
    im.src = src
    if cls:
        im.className = cls
    return im

def show_loading_cards():
    overlay = document.getElementById("loading-overlay")
    cards_box = document.getElementById("loading-cards")

    if not overlay or not cards_box:
        return

    clear_node(cards_box)
    overlay.classList.remove("hidden")

    back_url = _cards.getUrl(0)

    positions = [0, 55, 110, 165]

    for i, left in enumerate(positions):
        im = document.createElement("img")
        im.src = back_url
        im.className = "loading-card"
        im.style.left = f"{left}px"
        im.style.zIndex = str(i)
        cards_box.appendChild(im)

        # 少しずつ表示
        def make_show(img):
            def _show():
                img.classList.add("show")
            return _show

        window.setTimeout(make_show(im), i * 140)

def hide_loading_cards():
    overlay = document.getElementById("loading-overlay")
    if overlay:
        overlay.classList.add("hidden")

def set_img_src_initial(img, url: str):
    # 初回表示用：読み込み完了まで隠す
    img.classList.remove("ready")
    img.src = url

def set_img_src_smooth(img, url: str):
    # 通常更新用：隠さず、そのまま差し替える
    img.src = url
    img.classList.add("ready")

def render_cpu(panel_title_el, panel_cards_el, name: str, cards_list, pid: str):
    global reveal_cpu

    n = len(cards_list)
    panel_title_el.innerText = f"{name}（{n}枚） {win_rate_str(pid)}"

    clear_node(panel_cards_el)

    if n <= 0:
        panel_cards_el.style.minHeight = "70px"
        return

    # ★このCPUだけ表を見せる
    reveal = (reveal_cpu == pid)

    # 幅計算などは今まで通り（省略せずそのまま残す）
    w = int(panel_cards_el.clientWidth) if panel_cards_el.clientWidth else 260
    avail = max(120, w - 8)
    card_w = 56 if w < 240 else 52
    gap = 10

    # 8枚までは重ねない、超えたら重ねる
    threshold = 8
    total_normal = n * card_w + max(0, n - 1) * gap
    use_stack = (n > threshold) or (total_normal > avail)

    # stack用：自動で step_x を縮める（あなたの現行方針）    
    base_top = 2
    # 右端をはみ出しにくいように step_x を調整
    if use_stack:
        step_x = max(8, min(18, int((avail - card_w) / max(1, n - 1))))
    else:
        step_x = card_w + gap

    panel_cards_el.style.minHeight = "78px" if use_stack else "70px"

    for idx in range(n):
        # ★表or裏のURLを切り替える
        url = _cards.getUrl(cards_list[idx]) if reveal else _cards.getUrl(0)
        im = img_el(url, "cpu-card")

        if use_stack:
            im.classList.add("stack")
            im.style.left = f"{idx * step_x}px"
            im.style.top = f"{base_top}px"
            im.style.zIndex = str(idx)

        panel_cards_el.appendChild(im)

def render_you_title():
    n = len(you)
    stats = win_rate_str("you")
    you_title.innerText = f"あなた（{n}枚） {stats}"

def render_deck():
    deck_title.innerText = f"山のカード（{len(deck)}枚）"
    set_img_src_smooth(deck_img, _cards.getUrl(0))

    if len(deck) == 0 or has_playable():
        deck_img.classList.add("disabled")
    else:
        deck_img.classList.remove("disabled")

def render_field():
    if field is None:
        set_img_src_smooth(field_img, _cards.getUrl(0))
    else:
        set_img_src_smooth(field_img, _cards.getUrl(field))

def render_hand():
    global event_proxies

    # 古い proxy を破棄（クリックが増殖しないように）
    for p in event_proxies:
        try:
            p.destroy()
        except Exception:
            pass
    event_proxies = []

    clear_node(your_hand)

    card_ids = list(you)

    # コンテナ幅
    w = int(your_hand.clientWidth)
    pad = 28
    avail = max(200, w - pad)

    card_w = 140
    gap = 18

    n = len(card_ids)
    total_normal = n * card_w + max(0, n - 1) * gap
    use_stack = total_normal > avail

    # ★上余白：通常/重ねで切替（ホバーで上がっても切れない）
    your_hand.style.paddingTop = "70px" if use_stack else "38px"

    # 重ね表示のパラメータ
    step_x = 34
    step_y = 42
    base_top = 30

    # 1行に置ける枚数（重ね表示時）
    if use_stack:
        max_per_row = max(1, int((avail - card_w) // step_x) + 1)
        max_per_row = min(max_per_row, 18)
    else:
        max_per_row = n if n > 0 else 1

    # 段数（最大3段）
    rows = 1
    if use_stack and n > 0:
        rows = (n + max_per_row - 1) // max_per_row
        rows = min(rows, 3)

    # 高さ確保
    if use_stack:
        your_hand.style.minHeight = f"{260 + (rows - 1) * step_y}px"
    else:
        your_hand.style.minHeight = "240px"

    # 出せる/出せない（表示用）
    playable = set()
    if field is not None:
        for c in you:
            if can_play(c, field):
                playable.add(c)

    for idx, cid in enumerate(card_ids):
        im = img_el(_cards.getUrl(cid), "hand-card")
        im.dataset.cardId = str(cid)

        if selected == cid:
            im.classList.add("selected")

        if field is not None and cid not in playable:
            im.classList.add("disabled")

        # クリック handler（proxyで保持）
        def make_onclick(card_id):
            def _onclick(evt):
                asyncio.create_task(play_card(card_id))
            return _onclick

        handler = create_proxy(make_onclick(cid))
        event_proxies.append(handler)
        im.addEventListener("click", handler)

        # ★★★ ここが超安全：r/cidx を必ず定義してから使う ★★★
        r = 0
        cidx = idx

        if use_stack:
            r = idx // max_per_row
            cidx = idx % max_per_row
            if r >= 3:
                r = 2

            left = cidx * step_x
            top = base_top + r * step_y

            im.classList.add("stack")
            im.style.left = f"{left}px"
            im.style.top = f"{top}px"
            im.style.zIndex = str(idx)
        else:
            im.style.position = "static"

        your_hand.appendChild(im)


def render_all():
    render_cpu(cpuA_title, cpuA_cards, "プレーヤーA", cpuA, "cpuA")
    render_cpu(cpuB_title, cpuB_cards, "プレーヤーB", cpuB, "cpuB")
    render_cpu(cpuC_title, cpuC_cards, "プレーヤーC", cpuC, "cpuC")
    render_you_title()
    render_field()
    render_deck()
    render_hand()
    dobon_btn = document.getElementById("dobon-btn")
    if can_dobon():   # 判定関数
        dobon_btn.classList.add("ready")
    else:
        dobon_btn.classList.remove("ready") 

# ===== Actions =====
async def reset_async():
    global deck, field, discard
    global you, cpuA, cpuB, cpuC
    global busy, game_over, dobon_waiting
    global current_player_idx, current_player
    global selected, last_actor, last_winner
    global reveal_cpu
    
    # ブリンク解除
    for box in ["cpuA-box","cpuB-box","cpuC-box","you-box"]:
        el = document.getElementById(box)
        if el:
            el.classList.remove("win-blink")

    if busy:
        return
    busy = True
    try:
        await ensure_cards()

        show_loading_cards()

        # ===== 全フラグ完全リセット =====
        game_over = False
        dobon_waiting = False
        selected = None
        last_actor = None
        reveal_cpu = None        

        # ===== 先行プレイヤー決定 =====
        if last_winner is None:
        # 初回は you
            start_player = "you"
        else:
            # 前回の勝者
            start_player = last_winner

        current_player_idx = TURN_ORDER.index(start_player)
        current_player = TURN_ORDER[current_player_idx]


        set_dobon_alert(False)
        dobon_btn.disabled = False
        
        # シャッフル
        deck = list(range(1, 53))
        random.shuffle(deck)
        # ★ここで discard をクリア
        discard = []

        # 5枚ずつ配る
        you = [deck.pop() for _ in range(5)]
        cpuA = [deck.pop() for _ in range(5)]
        cpuB = [deck.pop() for _ in range(5)]
        cpuC = [deck.pop() for _ in range(5)]

        # 場に1枚（表）
        field = deck.pop()

        # 画像初期化（リンク切れ防止）
        set_img_src_initial(field_img, _cards.getUrl(field))
        set_img_src_initial(deck_img, _cards.getUrl(0))
        # UI初期化
        deck_img.classList.remove("disabled")
        dobon_btn.disabled = False
        set_dobon_alert(False)        
        
        render_all()

        set_turn_ui(current_player)

        set_msg(
            f"{name_ja(current_player)} から Newゲーム！\n"
            "同じ（マークか数字）／ない→山から取る",
            ok=True
        )
        await asyncio.sleep(0.5)
        hide_loading_cards() 
        
        if current_player in ("cpuA", "cpuB", "cpuC"):
            await asyncio.sleep(0.5)
            asyncio.create_task(run_cpu_turns_until_you())
                
        # 山札クリック
        def on_deck_click(evt):
            asyncio.create_task(draw_from_deck())

        # 二重登録防止のため、毎回入れ替え
        deck_img.onclick = on_deck_click

    finally:
        busy = False
       

async def tap_card(card_id: int):
    global selected

    # 1回目：選択
    if selected != card_id:
        selected = card_id
        render_hand()  # 選択表示だけ更新（全体render_allでもOK）
        return

    # 2回目：同じカード→出す試行
    await play_card(card_id)

async def play_card(card_id: int):
    global field, busy, selected, last_actor, cpu_running

    # ★CPUが動いている間は you は出せない（ドボンボタンだけ許す）
    if cpu_running or current_player != "you":
        set_msg("CPUの手番中です。ドボン以外はできません。", ng=True)
        return

    if busy:
        return
    busy = True
    try:
        if field is None:
            return

        # クリックしたカードが手札に存在しない（タイミング差）対策
        if card_id not in you:
            return
        
        # ★手札が1枚のときは「ドボン宣言」以外では上がれないので出せない
        if len(you) == 1:
            target = card_to_suit_rank(field)[1]
            total = card_to_suit_rank(you[0])[1]
            if total == target:
                set_msg("手札が1枚です。カードは出さずに「ドボン！」を押してください。", ok=True)
            else:
                set_msg("手札が1枚→ドボンのみ上がり。\nドボンできないので山から1枚取る。", ng=True)
            return

        if not can_play(card_id, field):
            set_msg("そのカードは場に出せません。\n（同じマーク か 同じ数字）", ng=True)
            return

        # 場に出す
        you.remove(card_id)

        # いまの場札を捨て札へ
        if field is not None:
            discard.append(field)
        # 新しい場札へ
        field = card_id
        selected = None

        # ★追加：この手番で“行動した人”を記録
        last_actor = "you"   # 将来CPU実装したら current_player で入れる

        set_msg("場に出しました。\n", ok=True)
        render_all()
        # you が行動したので次へ
        next_player()
        asyncio.create_task(run_cpu_turns_until_you())

    finally:
        busy = False


async def draw_from_deck():
    global busy, selected, last_actor

    # ★CPUが動いている間は you は引けない（ドボンボタンだけ許す）
    if cpu_running or current_player != "you":  
        set_msg("CPUの番です。ドボン以外ＮＧ。", ng=True)
        return

    if busy:
        return

    busy = True
    try:
        # ===== 山札補充チェック =====
        refilled = refill_deck_if_empty()

        if len(deck) == 0:
            set_msg("山札も捨て札もありません。\n", ng=True)
            return

        # ===== 出せるカードがあるなら引けない =====
        if has_playable():
            set_msg("出せるカードあり。→手札から出す。\n", ng=True)
            return

        # ===== 山札から引く =====
        c = deck.pop()
        you.append(c)
        selected = None

        # ★追加：引いたのも“行動”なので記録（次にドボンされたらこの人が負け）
        last_actor = "you"  # 将来CPU実装したら current_player で入れる

        # ===== メッセージ制御 =====
        if refilled:
            set_msg("山札を再構築しました。\n山札から1枚取りました。\n", ok=True)
        else:
            set_msg("山札から1枚取りました。\n", ok=True)

        render_all()
        next_player()
        asyncio.create_task(run_cpu_turns_until_you())

    finally:
        busy = False

def card_label(cid: int) -> str:
    s, r = card_to_suit_rank(cid)
    suit_symbol = {"C":"♣","D":"♦","H":"♥","S":"♠"}.get(s, s)
    return f"{suit_symbol}{r}"

def hand_sum(cards):
    return sum(card_to_suit_rank(cid)[1] for cid in cards)

async def try_dobon_async():
    global busy, dobon_waiting, last_actor

    if busy:
        return

    busy = True
    try:
        ok, used = dobon_possible()

        target = card_to_suit_rank(field)[1]
        total = sum(card_to_suit_rank(cid)[1] for cid in you)

        # ===== ワンクッション =====
        if ok and last_actor == "you":
            set_msg(
                "ドボン・準備完了！\n"
                "次の人の手番後に「ドボン！」できます。",
                ng=True
            )

            # CPU停止中なら再開
            if dobon_waiting:
                dobon_waiting = False
                set_dobon_alert(False)
                asyncio.create_task(run_cpu_turns_until_you())
            return

        # ===== ドボン失敗 =====
        if not ok:
            set_msg(
                f"ドボンできません。\n"
                f"手札の合計：{total}  場の数字：{target}",
                ng=True
            )

            if dobon_waiting:
                dobon_waiting = False
                set_dobon_alert(False)
                asyncio.create_task(run_cpu_turns_until_you())
            return

        # ===== 勝利（you）=====
        loser = last_actor if last_actor is not None else "（不明）"
        end_game_by_dobon("you", loser)
        return

    finally:
        busy = False


def try_dobon(event=None):
    asyncio.create_task(try_dobon_async())

def can_dobon():
    ok, _ = dobon_possible()
    return ok

def refill_deck_if_empty():
    """山札が空なら、場の一番上(field)だけ残して discard をシャッフルして山に戻す"""
    global deck, discard, field

    if len(deck) > 0:
        return False

    # discard が無ければ補充できない
    if len(discard) == 0:
        return False

    random.shuffle(discard)
    deck = discard[:]   # 山札に戻す
    discard = []        # 捨て札は空に
    return True

def set_turn_ui(player: str):
    # いったん全部OFF
    for pid in ["you-box", "cpuA-box", "cpuB-box", "cpuC-box"]:
        el = document.getElementById(pid)
        if el:
            el.classList.remove("turn-active")

    # ON
    box_id = {"you":"you-box","cpuA":"cpuA-box","cpuB":"cpuB-box","cpuC":"cpuC-box"}[player]
    el = document.getElementById(box_id)
    if el:
        el.classList.add("turn-active")


def name_ja(player: str) -> str:
    return {
        "you":"あなた",
        "cpuA":"プレーヤーA",
        "cpuB":"プレーヤーB",
        "cpuC":"プレーヤーC",
    }[player]

def next_player():
    global current_player_idx, current_player
    current_player_idx = (current_player_idx + 1) % len(TURN_ORDER)
    current_player = TURN_ORDER[current_player_idx]
    set_turn_ui(current_player)

def get_hand(player: str) -> list[int]:
    if player == "cpuA": return cpuA
    if player == "cpuB": return cpuB
    if player == "cpuC": return cpuC
    raise ValueError("player must be cpuA/cpuB/cpuC")

async def cpu_play(player: str, card_id: int):
    global field, selected, last_actor

    hand = get_hand(player)
    # タイミング差
    if card_id not in hand:
        await cpu_draw(player)
        return

    # 残り1枚は “ドボン宣言以外で上がれない” ルール（CPUにも同様に適用）
    if len(hand) == 1:
        await cpu_draw(player)
        return

    if not can_play(card_id, field):
        await cpu_draw(player)
        return

    # 捨て札へ
    if field is not None:
        discard.append(field)

    hand.remove(card_id)
    field = card_id

    # ★直前に行動した人（重要！）
    last_actor = player

    set_msg(f"{name_ja(player)} が場に出しました。\n", ok=True)
    render_all()

async def cpu_draw(player: str):
    global last_actor

    # 山札補充
    refill_deck_if_empty()
    if len(deck) == 0:
        set_msg("山札も捨て札もありません。\n", ng=True)
        return

    hand = get_hand(player)

    c = deck.pop()
    hand.append(c)

    # ★直前に行動した人（重要！）
    last_actor = player
    set_msg(f"{name_ja(player)} が山から1枚取りました。\n", ok=True)
    render_all()

async def run_cpu_turns_until_you():
    global busy, game_over, current_player, last_actor, dobon_waiting, cpu_running

    cpu_running = True
    try:
        while (not game_over) and current_player != "you":

            set_turn_ui(current_player)
            await asyncio.sleep(0.35)

            # ===== you優先：ドボンチャンスならCPU停止 =====
            if can_dobon() and last_actor != "you":
                dobon_waiting = True
                set_dobon_alert(True)
                set_msg("ドボンチャンス！「ドボン！」を押してください。\n", ok=True)
                return

            hand = get_hand(current_player)

            if field is None:
                next_player()
                continue

            # ===== CPU 即ドボン判定（行動前） =====
            if cpu_can_dobon(hand) and last_actor != current_player:
                loser = last_actor if last_actor else "（不明）"
                end_game_by_dobon(current_player, loser)
                return

            # ===== 行動選択 =====
            if len(hand) == 1:
                # ワンクッションルール
                chosen = None

            else:
                chosen = None

                # --- ① この1手で「次ターンドボン体制」を作れるか？ ---
                playable = [c for c in hand if can_play(c, field)]
                for c in playable:
                    new_hand = hand[:]
                    new_hand.remove(c)

                    # 出した直後は自分はドボン不可（ワンクッション）
                    # なので「次の自分の番でドボン可能形」になっているかを見る
                    if cpu_can_dobon(new_hand):
                        chosen = c
                        break

                # --- アルゴリズム ---
                if chosen is None:
                    if current_player == "cpuA":
                        chosen = choose_card_lv1(hand, field, can_play)

                    elif current_player == "cpuB":
                        chosen = choose_card_lv2_keep_field(hand, field, can_play)

                    elif current_player == "cpuC":
                        chosen = choose_card_lv3(
                            hand,
                            field,
                            can_play,
                            discard=discard,
                            you_hand_count=len(you),
                            other_counts=[len(cpuA), len(cpuB)],
                            keep_field_bias=True,
                        )
                    
                    else:
                        chosen = None

            # ===== 実行 =====
            if chosen is not None:
                await cpu_play(current_player, chosen)
            else:
                await cpu_draw(current_player)

            # ===== 行動後：youのドボン停止 =====
            if can_dobon() and last_actor != "you":
                dobon_waiting = True
                set_dobon_alert(True)
                set_msg("ドボンチャンス！「ドボン！」を押してください。\n", ok=True)
                return

            next_player()

    finally:
        cpu_running = False
        if not game_over:
            set_turn_ui("you")


def set_dobon_alert(on: bool):
    if on:
        dobon_btn.classList.add("dobon-alert")
    else:
        dobon_btn.classList.remove("dobon-alert")

def cpu_can_dobon(hand):
    if field is None or len(hand) == 0:
        return False
    target = card_to_suit_rank(field)[1]
    total = sum(card_to_suit_rank(c)[1] for c in hand)
    return total == target

def end_game_by_dobon(winner: str, loser: str):
    global game_over, dobon_waiting, reveal_cpu, last_winner

    game_over = True
    dobon_waiting = False
    set_dobon_alert(False)
    last_winner = winner

    # ★勝者がCPUなら表にする（you勝利ならNoneでOK）
    if winner in ("cpuA", "cpuB", "cpuC"):
        reveal_cpu = winner
    else:
        reveal_cpu = None
    # UI停止
    deck_img.classList.add("disabled")
    dobon_btn.disabled = True

    # 勝敗表示（ここが上書きされないのが大事）
    set_msg(f"{name_ja(winner)} がドボン！\n負け：{name_ja(loser)}", ok=True)

    # 勝率更新もここで
    if winner in win_stats:
        win_stats[winner]["win"] += 1
    for p in win_stats:
        win_stats[p]["total"] += 1

    # ===== 勝者ブリンク演出 =====
    for box in ["cpuA-box","cpuB-box","cpuC-box","you-box"]:
        el = document.getElementById(box)
        if el:
            el.classList.remove("win-blink")

    win_box = {
        "cpuA": "cpuA-box",
        "cpuB": "cpuB-box",
        "cpuC": "cpuC-box",
        "you": "you-box",
    }.get(winner)

    if win_box:
        el = document.getElementById(win_box)
        if el:
            el.classList.add("win-blink")

    render_all()

# ===== PyScript entry points =====
def reset_game(event=None):
    global last_actor, dobon_waiting, game_over

    last_actor = None
    dobon_waiting = False
    game_over = False

    set_dobon_alert(False)
    dobon_btn.disabled = False

    asyncio.create_task(reset_async())
    
# init
asyncio.create_task(reset_async())

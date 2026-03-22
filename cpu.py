# CPUの思考ロジック（レベル別）

def rank_of(card_id: int) -> int:
    return ((card_id - 1) % 13) + 1  # 1..13

def suit_of(card_id: int) -> int:
    return (card_id - 1) // 13  # 0..3

def total_rank(hand: list[int]) -> int:
    return sum(rank_of(c) for c in hand)

def count_pairs_by_rank(hand: list[int]) -> int:
    """同じ数字のペア数（例：5が2枚なら1、5が3枚なら1扱いでもOK。ここは“2枚組”で数える）"""
    from collections import Counter
    cnt = Counter(rank_of(c) for c in hand)
    return sum(v // 2 for v in cnt.values())

def has_split_sum_structure(hand: list[int]) -> bool:
    """
    例：7 と (4+3) みたいな “分割” を作りやすい構造があるか（教育的な「ドボン体制」）。
    厳密勝率より「体制を崩さない」方向に効く軽いボーナス。
    """
    ranks = [rank_of(c) for c in hand]
    s = set(ranks)
    for t in range(2, 14):  # 2..13
        # t を (a+b) に分解できるカードがあるか
        for a in range(1, t):
            b = t - a
            if a in s and b in s:
                return True
    return False

def choose_card_lv1(hand: list[int], field: int, can_play: Callable[[int, int], bool]) -> Optional[int]:
    playable = [c for c in hand if can_play(c, field)]
    if not playable:
        return None
    playable.sort(key=lambda c: rank_of(c), reverse=True)
    return playable[0]

# ===== lv2 用 =====

def count_pairs_by_rank(hand: list[int]) -> int:
    from collections import Counter
    cnt = Counter(rank_of(c) for c in hand)
    return sum(v // 2 for v in cnt.values())

def has_split_sum_structure(hand: list[int]) -> bool:
    ranks = [rank_of(c) for c in hand]
    s = set(ranks)
    for t in range(2, 14):
        for a in range(1, t):
            b = t - a
            if a in s and b in s:
                return True
    return False

def choose_card_lv2(
    hand: list[int],
    field: int,
    can_play: Callable[[int, int], bool],
    *,
    keep_field: bool = False,
) -> Optional[int]:
    """
    lv2（中）: “ドボン圏(合計1..13)に寄せる” + “体制(ペア/分割)を崩しにくい” + “大きいカードを優先して捨てる”
    keep_field=True にすると「場を動かさない」寄り（同じ数字を出す）を強める
    """
    if field is None:
        return None

    playable = [c for c in hand if can_play(c, field)]
    if not playable:
        return None

    field_rank = rank_of(field)

    # 現在の“体制”を把握（これを減らしにくい手を好む）
    base_pairs = count_pairs_by_rank(hand)
    base_split = has_split_sum_structure(hand)
    base_total = total_rank(hand)

    best = None
    best_score = -10**18

    for c in playable:
        new_hand = hand[:]         # shallow copy
        new_hand.remove(c)

        # ルール上、残り1枚は出せない運用があるので、ここでも保険
        if len(new_hand) == 0:
            continue

        new_total = total_rank(new_hand)

        # “体制”変化
        new_pairs = count_pairs_by_rank(new_hand)
        new_split = has_split_sum_structure(new_hand)

        # -------------------------
        # スコア設計（ここがlv2の肝）
        # -------------------------
        score = 0

        # 1) 最重要：合計をドボン圏(1..13)に入れる
        if 1 <= new_total <= 13:
            score += 5000
            # 圏内でも、小さい方が次の調整が効くので少しだけ優遇
            score += (13 - new_total) * 15
        else:
            # 圏外は強烈に罰（大きいほどさらに罰）
            score -= 5000
            score -= (new_total - 13) * 50

        # 2) 大きいカードを切る（合計を下げるのに効く）
        score += rank_of(c) * 30

        # 3) “同ランクペア”を残す（体制維持）
        if new_pairs > base_pairs:
            score += 250
        elif new_pairs < base_pairs:
            score -= 350  # ペアを壊すのは嫌

        # 4) “分割体制”を残す（軽いボーナス）
        if (not base_split) and new_split:
            score += 120
        elif base_split and (not new_split):
            score -= 120

        # 5) 「場を動かさない」版（任意）
        # 同じ数字を出す＝次の人に“合わせやすい”面もあるので、強すぎない加点にしている
        if keep_field and rank_of(c) == field_rank:
            score += 180

        # 6) 追加：合計を下げる方向を好む（現状より合計が減るほど加点）
        score += (base_total - new_total) * 8

        # tie-break：同点なら「より大きいカードを出す」を優先
        if (score > best_score) or (score == best_score and (best is None or rank_of(c) > rank_of(best))):
            best_score = score
            best = c

    return best

def choose_card_lv2_keep_field(hand: list[int], field: int, can_play: Callable[[int, int], bool]) -> Optional[int]:
    """lv2の『場を動かさない』寄り版"""
    return choose_card_lv2(hand, field, can_play, keep_field=True)

# ===== lv3 用 =====

def seen_rank_counts(discard: list[int], field: Optional[int]) -> dict[int, int]:
    counts = {r: 0 for r in range(1, 14)}
    for c in discard:
        counts[rank_of(c)] += 1
    if field is not None:
        counts[rank_of(field)] += 1
    return counts

def remaining_rank_estimate(rank: int, discard: list[int], field: Optional[int]) -> int:
    # 各数字は4枚ずつ存在
    seen = seen_rank_counts(discard, field)
    return max(0, 4 - seen[rank])

def danger_score_for_target(
    target_rank: int,
    you_hand_count: int,
    other_counts: list[int],
    discard: list[int],
    field: Optional[int],
) -> int:
    """
    場を target_rank にしたとき、相手にドボンされる危険度の概算
    """
    danger = 0

    remain = remaining_rank_estimate(target_rank, discard, field)

    # 残り枚数が少ない相手ほど危険
    if you_hand_count <= 2:
        danger += 900
    elif you_hand_count <= 3:
        danger += 500
    elif you_hand_count <= 4:
        danger += 250

    for n in other_counts:
        if n <= 2:
            danger += 600
        elif n <= 3:
            danger += 300

    # 小さい数字ほどドボンしやすい
    if target_rank <= 5:
        danger += 260
    elif target_rank <= 8:
        danger += 120

    # まだその数字が多く残っているほど危険
    danger += remain * 90

    return danger

def choose_card_lv3(
    hand: list[int],
    field: int,
    can_play: Callable[[int, int], bool],
    *,
    discard: list[int],
    you_hand_count: int,
    other_counts: list[int],
    keep_field_bias: bool = True,
) -> Optional[int]:
    """
    lv3:
    - 自分のドボン圏を作る
    - 相手の危険度を下げる
    - 場に出たカード(discard + field)を利用して残り数字を推定
    - ただし、ドボン圏に入ったら「攻めモード」に切り替える
    """
    if field is None:
        return None

    playable = [c for c in hand if can_play(c, field)]
    if not playable:
        return None

    field_rank = rank_of(field)
    base_pairs = count_pairs_by_rank(hand)
    base_split = has_split_sum_structure(hand)
    base_total = total_rank(hand)

    best = None
    best_score = -10**18

    for c in playable:
        new_hand = hand[:]
        new_hand.remove(c)

        # 残り0枚は通常の出し方では不可
        if len(new_hand) == 0:
            continue

        new_total = total_rank(new_hand)
        new_pairs = count_pairs_by_rank(new_hand)
        new_split = has_split_sum_structure(new_hand)

        # このカードを出した後、場の数字は「出したカードの数字」になる
        next_target = rank_of(c)

        score = 0

        # ===== 1. 勝ち筋：ドボン圏へ =====
        if 1 <= new_total <= 13:
            # ドボン圏に入ったら大幅加点
            score += 7000
            score += (13 - new_total) * 20

            # 小さい数ほどドボンしやすいのでさらに加点
            if new_total <= 5:
                score += 2000
            elif new_total <= 8:
                score += 800
        else:
            # 圏外は強く減点
            score -= 6000
            score -= (new_total - 13) * 60

        # 次ターンでドボンしやすい形
        if new_pairs > 0:
            score += 280
        if new_split:
            score += 180

        # ===== 2. 体制維持 =====
        if new_pairs > base_pairs:
            score += 260
        elif new_pairs < base_pairs:
            score -= 400

        if (not base_split) and new_split:
            score += 150
        elif base_split and (not new_split):
            score -= 150

        # ===== 3. 大きいカードを切って手札合計を下げる =====
        score += rank_of(c) * 28
        score += (base_total - new_total) * 10

        # ===== 4. 危険回避 =====
        danger = danger_score_for_target(
            next_target,
            you_hand_count=you_hand_count,
            other_counts=other_counts,
            discard=discard,
            field=field,
        )

        # ドボン圏に入ったら少し攻める
        if 1 <= new_total <= 13:
            score -= danger * 0.4
        else:
            score -= danger

        # ===== 5. 場を動かさない補正（弱め） =====
        if keep_field_bias and rank_of(c) == field_rank:
            score += 90

        # tie-break
        if (score > best_score) or (
            score == best_score and (best is None or rank_of(c) > rank_of(best))
        ):
            best_score = score
            best = c

    return best

"""Xiangqi coordinates use black at the top, red at the bottom, a0 at bottom left."""
from collections import Counter
import re

START_FEN = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"
NAMES = dict(zip("RNBAKCP", "车马相仕帅炮兵")) | dict(zip("rnbakcp", "车马象士将炮卒"))
RED_NUMBERS = "一二三四五六七八九"


def parse_fen(fen):
    fields = fen.strip().split()
    if len(fields) != 6 or fields[1] not in ("w", "b"):
        raise ValueError("FEN 需包含完整的六个字段，w 为红走，b 为黑走")
    board = []
    for rank in fields[0].split("/"):
        row = []
        for p in rank:
            if p in "123456789":
                row.extend([""] * int(p))
            elif p in NAMES:
                row.append(p)
            else:
                raise ValueError("FEN 包含无效棋子")
        board.append(row)
    validate(board)
    return board, "red" if fields[1] == "w" else "black"


def to_fen(board, turn, halfmove=0, fullmove=1):
    ranks = []
    for row in board:
        rank, blank = "", 0
        for p in row:
            if not p:
                blank += 1
            else:
                if blank:
                    rank += str(blank)
                    blank = 0
                rank += p
        if blank:
            rank += str(blank)
        ranks.append(rank)
    return "/".join(ranks) + f" {'w' if turn == 'red' else 'b'} - - {halfmove} {fullmove}"


def color(p):
    return ("red" if p.isupper() else "black") if p and p in NAMES else None


def opposite(turn):
    return "black" if turn == "red" else "red"


def square(x, y):
    return chr(97 + x) + str(9 - y)


def decode_move(move):
    if not re.fullmatch(r"[a-i][0-9][a-i][0-9]", move):
        raise ValueError("无效走法坐标")
    return (ord(move[0])-97, 9-int(move[1])), (ord(move[2])-97, 9-int(move[3]))


def apply_move(board, move):
    (x, y), (u, v) = decode_move(move)
    result = [row[:] for row in board]
    result[v][u], result[y][x] = result[y][x], ""
    return result


def validate(board):
    if len(board) != 10 or any(len(row) != 9 for row in board):
        raise ValueError("棋盘必须是 9 列 10 行")
    counts = Counter(p for row in board for p in row if p)
    if any(p not in NAMES for p in counts):
        raise ValueError("有棋子尚未识别，请校正")
    for side in ("red", "black"):
        convert = str.upper if side == "red" else str.lower
        if counts[convert("k")] != 1:
            raise ValueError("双方应各有一枚帅或将")
        for p, maximum in (("r",2),("n",2),("b",2),("a",2),("c",2),("p",5)):
            if counts[convert(p)] > maximum:
                raise ValueError(f"{side == 'red' and '红' or '黑'}方{NAMES[convert(p)]}数量异常")
    red_advisors = {(3,9),(5,9),(4,8),(3,7),(5,7)}
    red_elephants = {(2,9),(6,9),(0,7),(4,7),(8,7),(2,5),(6,5)}
    for y,row in enumerate(board):
        for x,p in enumerate(row):
            if not p:
                continue
            red = p.isupper()
            cx,cy = (x,y) if red else (8-x,9-y)
            if p.lower() == "k" and not (3 <= cx <= 5 and 7 <= cy <= 9):
                raise ValueError("帅或将应位于九宫内，请检查棋盘方向")
            if p.lower() == "a" and (cx,cy) not in red_advisors:
                raise ValueError("仕或士位置异常")
            if p.lower() == "b" and (cx,cy) not in red_elephants:
                raise ValueError("相或象位置异常")
            if p.lower() == "p" and (cy > 6 or (cy >= 5 and cx % 2)):
                raise ValueError("兵或卒位置异常")
    if in_check(board,"red") and in_check(board,"black"):
        raise ValueError("双方同时被将军，请检查识别")
    return {"red":sum(n for p,n in counts.items() if p.isupper()),
            "black":sum(n for p,n in counts.items() if p.islower())}


def _attacks(board, x, y, u, v):
    p = board[y][x]
    dx,dy = u-x,v-y
    ax,ay = abs(dx),abs(dy)
    kind = p.lower()
    red = p.isupper()
    if kind in ("r","c"):
        if bool(dx) == bool(dy):
            return False
        sx,sy = (0 if dx == 0 else (1 if dx > 0 else -1)), (0 if dy == 0 else (1 if dy > 0 else -1))
        tx,ty,count = x+sx,y+sy,0
        while (tx,ty) != (u,v):
            count += bool(board[ty][tx])
            tx,ty = tx+sx,ty+sy
        return count == (1 if kind == "c" and board[v][u] else 0)
    if kind == "n":
        return ((ax,ay) == (2,1) and not board[y][x+dx//2]) or ((ax,ay) == (1,2) and not board[y+dy//2][x])
    if kind == "b":
        return ax == ay == 2 and (v >= 5 if red else v <= 4) and not board[y+dy//2][x+dx//2]
    if kind == "a":
        return ax == ay == 1 and 3 <= u <= 5 and (7 <= v <= 9 if red else 0 <= v <= 2)
    if kind == "k":
        if dx == 0 and board[v][u].lower() == "k":
            return not any(board[t][x] for t in range(min(y,v)+1,max(y,v)))
        return ax+ay == 1 and 3 <= u <= 5 and (7 <= v <= 9 if red else 0 <= v <= 2)
    if kind == "p":
        return (dx == 0 and dy == (-1 if red else 1)) or (dy == 0 and ax == 1 and (y <= 4 if red else y >= 5))
    return False


def in_check(board, turn):
    king = "K" if turn == "red" else "k"
    location = next(((x,y) for y,row in enumerate(board) for x,p in enumerate(row) if p == king),None)
    if location is None:
        return True
    u,v = location
    return any(color(p) == opposite(turn) and _attacks(board,x,y,u,v)
               for y,row in enumerate(board) for x,p in enumerate(row) if p)


def legal_moves(board, turn):
    moves = []
    for y,row in enumerate(board):
        for x,p in enumerate(row):
            if color(p) != turn:
                continue
            for v in range(10):
                for u in range(9):
                    target = board[v][u]
                    if color(target) == turn or target.lower() == "k" or not _attacks(board,x,y,u,v):
                        continue
                    move = square(x,y)+square(u,v)
                    if not in_check(apply_move(board,move),turn):
                        moves.append(move)
    return moves


def transition(previous, current, turn):
    changes = [(x,y) for y in range(10) for x in range(9) if previous[y][x] != current[y][x]]
    if len(changes) != 2:
        return None
    sources = [(x,y) for x,y in changes if previous[y][x] and not current[y][x]]
    if len(sources) != 1:
        return None
    x,y = sources[0]
    u,v = next(pt for pt in changes if pt != (x,y))
    move = square(x,y)+square(u,v)
    side = color(previous[y][x])
    if turn and side != turn:
        return None
    if current[v][u] != previous[y][x] or move not in legal_moves(previous,side):
        return None
    return move, opposite(side)


def transition_path(previous, current, turn):
    single=transition(previous,current,turn)
    if single:
        move,next_turn=single
        return [move],next_turn
    if turn not in ("red","black"):
        return None
    changes=sum(previous[y][x]!=current[y][x] for y in range(10) for x in range(9))
    if not 2<=changes<=4:
        return None
    # A fast opponent may reply between stable frames. Accept only one legal two-ply path.
    matches=[]
    for first in legal_moves(previous,turn):
        intermediate=apply_move(previous,first)
        second=transition(intermediate,current,opposite(turn))
        if second:
            move,next_turn=second
            matches.append(([first,move],next_turn))
            if len(matches)>1:
                return None
    return matches[0] if matches else None


def match_observation(previous, sides, turn):
    """Resolve piece identities only from a unique legal path and every cell's observed color."""
    if len(sides)!=10 or any(len(row)!=9 for row in sides):
        return None
    if any(side not in ("","red","black") for row in sides for side in row):
        return None
    previous_sides=[[color(p) or "" for p in row] for row in previous]
    if previous_sides==sides:
        return previous,[],turn
    if turn not in ("red","black"):
        return None
    changed=sum(a!=b for row,seen in zip(previous_sides,sides) for a,b in zip(row,seen))
    if not 2<=changed<=4:
        return None
    matches=[]
    for first in legal_moves(previous,turn):
        (x,y),_=decode_move(first)
        if sides[y][x]==turn:
            continue
        intermediate=apply_move(previous,first)
        inter_sides=[[color(p) or "" for p in row] for row in intermediate]
        if inter_sides==sides:
            matches.append((intermediate,[first],opposite(turn)))
            continue
        differences=[(u,v) for v in range(10) for u in range(9) if inter_sides[v][u]!=sides[v][u]]
        if len(differences)!=2:
            continue
        sources=[(u,v) for u,v in differences if inter_sides[v][u]==opposite(turn) and not sides[v][u]]
        if len(sources)!=1:
            continue
        source=sources[0]
        destination=next(pt for pt in differences if pt!=source)
        u,v=destination
        if sides[v][u]!=opposite(turn):
            continue
        second=square(*source)+square(*destination)
        if second in legal_moves(intermediate,opposite(turn)):
            matches.append((apply_move(intermediate,second),[first,second],turn))
        if len(matches)>1:
            return None
    return matches[0] if len(matches)==1 else None


def notation(board, move):
    (x,y),(u,v) = decode_move(move)
    p = board[y][x]
    if not p:
        return move
    red = p.isupper()
    number = lambda n: RED_NUMBERS[n-1] if red else str(n)
    file_number = lambda column: 9-column if red else column+1
    same_file = [r for r in range(10) if board[r][x] == p]
    same_file.sort(reverse=not red)
    if len(same_file) == 2:
        prefix = ("前" if y == same_file[0] else "后") + NAMES[p]
    elif len(same_file) > 2:
        index = same_file.index(y)
        prefix = ("前" if index == 0 else "后" if index == len(same_file)-1 else "中" if len(same_file)==3 else number(index+1)) + NAMES[p]
    else:
        prefix = NAMES[p] + number(file_number(x))
    if y == v:
        return prefix + "平" + number(file_number(u))
    forward = v < y if red else v > y
    suffix = file_number(u) if p.lower() in "nba" else abs(v-y)
    return prefix + ("进" if forward else "退") + number(suffix)


START_BOARD = parse_fen(START_FEN)[0]

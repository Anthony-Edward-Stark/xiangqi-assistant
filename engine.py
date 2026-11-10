"""Serialized UCI sessions, bounded search and validation through official Pikafish."""
import queue
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from rules import apply_move, decode_move, legal_moves, notation, opposite, to_fen, validate

ROOT = Path(__file__).resolve().parent
NETWORK_GUIDE = "Pikafish 2026-09-06 官方发布包内的 pikafish.nnue"


class SearchCancelled(Exception):
    pass


def physical_threads():
    try:
        cores=int(subprocess.check_output(["/usr/sbin/sysctl","-n","hw.physicalcpu"],timeout=2))
    except (OSError,ValueError,subprocess.SubprocessError):
        cores=os.cpu_count() or 2
    return max(1,min(2,cores))


class Engine:
    def __init__(self, threads=None, hash_mb=256, network=None):
        self.process = None
        self.lines = None
        self.lock = threading.RLock()
        self.closed = False
        self.threads = threads or physical_threads()
        self.hash_mb = hash_mb
        self.network = Path(network) if network is not None else ROOT/"engine/pikafish.nnue"
        self.cancel_event = None
        self.reset_requested = threading.Event()
        self.game_fen = None
        self.game_moves = ()

    def _write(self, command):
        self.process.stdin.write(command+"\n")
        self.process.stdin.flush()

    def _read_until(self, predicate, timeout):
        end = time.monotonic()+timeout
        result = []
        while time.monotonic() < end:
            try:
                line = self.lines.get(timeout=max(.01,end-time.monotonic()))
            except queue.Empty:
                break
            if line is None:
                raise RuntimeError("Pikafish 已退出：" + " / ".join(result[-4:]))
            result.append(line)
            if predicate(line):
                return result
        raise TimeoutError("Pikafish 响应超时")

    def _start(self):
        if self.closed:
            raise RuntimeError("引擎已关闭")
        if self.process and self.process.poll() is None:
            return
        network=self.network if self.network.is_file() else ROOT/"engine/pikafish.nnue"
        if not network.is_file():
            raise FileNotFoundError(f"请将 {NETWORK_GUIDE} 放入 {self.network.parent.resolve()} 后重启助手。")
        network=network.resolve()
        if "\n" in str(network) or "\r" in str(network):
            raise ValueError("权重文件路径不能含换行符")
        self.lines = queue.Queue()
        self.process = subprocess.Popen([str(ROOT/"engine/pikafish")],cwd=ROOT/"engine",
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
        process,lines = self.process,self.lines
        def reader():
            for line in process.stdout:
                lines.put(line.strip())
            lines.put(None)
        threading.Thread(target=reader,daemon=True).start()
        self._write("uci")
        self._read_until(lambda line: line == "uciok",15)
        self.game_fen=None
        self.game_moves=()
        for command in (f"setoption name Threads value {self.threads}",f"setoption name Hash value {self.hash_mb}",
                        "setoption name MultiPV value 1","setoption name Ponder value false",
                        f"setoption name EvalFile value {network}","isready"):
            self._write(command)
        self._read_until(lambda line: line == "readyok",15)

    def _position(self, board, turn, history):
        if history:
            return "position fen " + history["fen"] + (" moves " + " ".join(history["moves"]) if history["moves"] else "")
        return "position fen " + to_fen(board,turn)

    def _kill(self):
        if self.process:
            if self.process.poll() is None:
                self.process.kill()
            self.process.wait(timeout=5)
            for stream in (self.process.stdin,self.process.stdout):
                stream.close()
        self.process = None

    def perft_moves(self, board, turn):
        validate(board)
        with self.lock:
            try:
                self._start()
                self._write(self._position(board,turn,None))
                self._write("go perft 1")
                output = self._read_until(lambda line:line.startswith("Nodes searched:"),10)
                return sorted(match.group(1) for line in output if (match:=re.match(r"^([a-i][0-9][a-i][0-9]):",line)))
            except Exception:
                self._kill()
                raise

    @staticmethod
    def _info(line):
        if not line.startswith("info depth ") or " pv " not in line:
            return None
        tokens=line.split()
        if "lowerbound" in tokens or "upperbound" in tokens:
            return None
        try:
            info={name:int(tokens[tokens.index(name)+1]) for name in ("depth","seldepth","nodes","time","nps","hashfull") if name in tokens}
            if "multipv" in tokens and tokens[tokens.index("multipv")+1]!="1":
                return None
            if "score" in tokens:
                i=tokens.index("score")
                info["score"]={"type":tokens[i+1],"value":int(tokens[i+2])}
            info["pv"]=tokens[tokens.index("pv")+1:]
            return info if info["pv"] else None
        except (IndexError,ValueError):
            return None

    @staticmethod
    def _suggestion(board, turn, move, info, started, partial=False):
        continuation,position,side=[],board,turn
        for candidate in info.get("pv",[move])[:8]:
            if candidate not in legal_moves(position,side):
                break
            continuation.append({"move":candidate,"text":notation(position,candidate),"turn":side})
            position,side=apply_move(position,candidate),opposite(side)
        origin,destination=decode_move(move)
        return {**info,"move":move,"from":origin,"to":destination,"text":notation(board,move),
                "turn":turn,"continuation":continuation,"partial":partial,
                "engine_ms":round((time.perf_counter()-started)*1000,1)}

    def cancel(self):
        event=self.cancel_event
        if event:
            event.set()

    def request_reset(self):
        self.reset_requested.set()
        self.cancel()

    def analyse(self, board, turn, budget_ms=5000, history=None, on_update=None, cancel=None):
        validate(board)
        expected = legal_moves(board,turn)
        if not expected:
            return {"finished":True,"turn":turn}
        with self.lock:
            started=time.perf_counter()
            event=cancel or threading.Event()
            self.cancel_event=event
            try:
                if event.is_set():
                    raise SearchCancelled()
                self._start()
                fen=history["fen"] if history else to_fen(board,turn)
                moves=tuple(history.get("moves",())) if history else ()
                reused=not self.reset_requested.is_set() and fen==self.game_fen and moves[:len(self.game_moves)]==self.game_moves
                if not reused:
                    self.reset_requested.clear()
                    self._write("ucinewgame")
                    self._write("isready")
                    self._read_until(lambda line:line=="readyok",10)
                self.game_fen,self.game_moves=fen,moves
                if event.is_set():
                    raise SearchCancelled()
                self._write(self._position(board,turn,history))
                self._write(f"go movetime {budget_ms}")
                deadline=time.monotonic()+budget_ms/1000+8
                stopping=False
                infos={}
                network_error=False
                reported=time.monotonic()
                while True:
                    now=time.monotonic()
                    if event.is_set() and not stopping:
                        self._write("stop")
                        stopping=True
                        deadline=now+3
                    if now>=deadline:
                        raise TimeoutError("Pikafish 响应超时")
                    try:
                        line=self.lines.get(timeout=min(.1,deadline-now))
                    except queue.Empty:
                        continue
                    if line is None:
                        if network_error:
                            raise RuntimeError(f"棋力权重未能加载，请使用 {NETWORK_GUIDE}。")
                        raise RuntimeError("Pikafish 已退出")
                    if line.startswith("info string ERROR:") and "Network evaluation parameters" in line:
                        network_error=True
                    if line.startswith("bestmove "):
                        move=line.split()[1]
                        break
                    info=self._info(line)
                    if info and info["pv"][0] in expected:
                        infos[info["pv"][0]]=info
                        if on_update and not stopping and info.get("depth",0)>=6 and now-reported>=.25:
                            on_update(self._suggestion(board,turn,info["pv"][0],info,started,True))
                            reported=now
                if stopping or event.is_set():
                    raise SearchCancelled()
                if move in ("0000","(none)"):
                    return {"finished":True,"turn":turn}
                if move not in expected:
                    raise RuntimeError("引擎返回的走法与当前棋盘不一致")
                result=self._suggestion(board,turn,move,infos.get(move,{}),started)
                result.update(cache_reused=reused,threads=self.threads,hash_mb=self.hash_mb)
                return result
            except SearchCancelled:
                raise
            except Exception:
                self._kill()
                raise
            finally:
                if self.cancel_event is event:
                    self.cancel_event=None

    def close(self):
        self.cancel()
        with self.lock:
            self.closed=True
            if self.process and self.process.poll() is None:
                try:
                    self._write("quit")
                    self.process.wait(timeout=3)
                except (OSError,subprocess.TimeoutExpired):
                    pass
            self._kill()

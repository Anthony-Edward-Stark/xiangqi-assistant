"""Local USB-screen Xiangqi observer. Suggestions never send input to the phone."""
import argparse
import copy
import json
import os
import signal
import subprocess
import threading
import time
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
import cv2
import numpy as np
from browser_capture import BrowserCapture, LIVE_SOURCES, WINDOW_SOURCE, handle_capture
from engine import Engine, SearchCancelled
from rules import START_BOARD, color, in_check, opposite, parse_fen, to_fen, transition_path, match_observation, validate
from vision import Grid, Recognizer, detect_grid

ROOT=Path(__file__).resolve().parent
BUDGETS=(250,500,1000,2000,5000,10000,20000,30000)
MESSAGES={
    "waiting_window": "请选择 iPhone 投屏窗口",
    "waiting_capture":"等待 iPhone USB 屏幕", "capture_stopped":"取屏已停止", "stale":"画面已过期，建议已清空",
    "capture_starting":"iPhone 已连接，正在启动 USB 画面",
    "capture_unavailable":"USB 屏幕设备暂不可用，请检查手机解锁状态和 USB 连接",
    "capture_no_frames":"已检测到 iPhone，但没有收到画面，请保持解锁并重新插拔 USB",
    "multiple_devices":"检测到多台可取屏设备，请保留当前使用的 iPhone 连接",
    "capture_error":"USB 取屏失败，请检查手机解锁状态和 USB 连接",
    "no_grid":"未找到完整象棋棋盘", "need_templates":"请显示完整开局，学习当前皮肤的棋子",
    "uncertain":"有棋子无法确认，请保持清晰画面或校正局面", "invalid_position":"棋子位置异常，请检查识别",
    "need_turn":"请确认当前轮到红方还是黑方走", "stabilizing":"等待两帧一致的棋盘", "thinking":"正在深入计算，建议持续更新",
    "ready":"建议已更新", "opponent_turn":"等待对方走子", "paused":"分析已暂停", "finished":"当前走子方已无可走棋步",
    "error":"分析失败"
}


def atomic_json(path, data):
    temporary=path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    temporary.replace(path)


class Observer:
    def __init__(self, session, image=None, browser_capture=False):
        self.session=Path(session)
        self.session.mkdir(parents=True,exist_ok=True)
        self.image=Path(image) if image else None
        self.browser_capture = BrowserCapture() if browser_capture and not image else None
        self.input_source = "offline_image" if image else WINDOW_SOURCE if self.browser_capture else "live_usb_screen"
        self.lock=threading.RLock()
        self.stop=threading.Event()
        self.engine=Engine(network=self.session/"pikafish.nnue")
        self.recognizer=Recognizer(self.session/"piece-templates.npz")
        self.settings={"my_color":"red","orientation":"auto","budget_ms":5000,"paused":False}
        try:
            saved=json.loads((self.session/"settings.json").read_text(encoding="utf-8"))
            for key,allowed in (("my_color",("red","black","both")),("orientation",("auto","red_bottom","black_bottom")),
                                ("budget_ms",BUDGETS)):
                if saved.get(key) in allowed:
                    self.settings[key]=saved[key]
        except (OSError,ValueError,AttributeError):
            pass
        self.grid=self.recognizer.learned_grid
        self.manual_grid=None
        self.frame=b""
        self.state={"status": "waiting_window" if self.browser_capture else "waiting_capture","source": self.input_source,
                    "board":None,"suggestion":None,"captured_at":None,"frame_id":None,"turn":None,
                    "orientation":None,"position":None,"history_complete":False}
        self.generation=0
        self.seen_key=None
        self.stable_count=0
        self.analysis_key=None
        self.inflight=None
        self.analysis_cancel=None
        self.last_token=None
        self.detect_at=0
        self.tracked_board=None
        self.tracked_orientation=None
        self.turn=None
        self.history=None
        self.manual=False

    def snapshot(self):
        with self.lock:
            s=copy.deepcopy(self.state)
            s["browser_capture"] = bool(self.browser_capture)
            s["settings"]=dict(self.settings)
            s["grid"]=self.grid.to_dict() if self.grid else None
            s["templates_ready"]=len(self.recognizer.templates)==14
            date=s.get("captured_at")
            s["frame_age_ms"]=max(0,round((time.time()-date)*1000)) if date else None
            if s["source"] in LIVE_SOURCES and date and time.time()-date>2:
                s.update(status="stale",suggestion=None,board=None,position=None,turn=None)
            s["message"]=s.get("error") or MESSAGES.get(s["status"],s["status"])
            if s.get("board") and s.get("turn") and not any("?" in row for row in s["board"]):
                s["fen"]=to_fen(s["board"],s["turn"])
            return s

    def invalidate(self, status, error=None, clear_board=True):
        with self.lock:
            if self.analysis_cancel:
                self.analysis_cancel.set()
            if self.state["status"]!=status or self.state.get("suggestion"):
                self.generation+=1
            self.state.update(status=status,error=error,suggestion=None)
            if clear_board:
                self.state.update(board=None,position=None,turn=None,last_move=None)
            elif status in ("uncertain","need_templates","invalid_position"):
                self.state.update(position=None,turn=None,last_move=None)
            self.seen_key=None
            self.stable_count=0
            self.analysis_key=None

    def configure(self, values):
        with self.lock:
            settings=dict(self.settings)
            for key,allowed in (("my_color",("red","black","both")),("orientation",("auto","red_bottom","black_bottom")),
                                ("budget_ms",BUDGETS)):
                if key in values:
                    if values[key] not in allowed or isinstance(values[key],bool):
                        raise ValueError("无效设置："+key)
                    settings[key]=values[key]
            if "paused" in values:
                if type(values["paused"]) is not bool:
                    raise ValueError("暂停参数应为布尔值")
                settings["paused"]=values["paused"]
            orientation_changed=settings["orientation"]!=self.settings["orientation"]
            self.settings=settings
            atomic_json(self.session/"settings.json",settings)
            self.generation+=1
            self.analysis_key=None
            if orientation_changed:
                self.tracked_board=self.history=None
                self.tracked_orientation=None
                self.turn=None
            self.invalidate("paused" if settings["paused"] else "stabilizing",clear_board=False)
            return self.snapshot()

    def reset_grid(self):
        with self.lock:
            self.manual=False
            self.grid=self.manual_grid=None
            self.detect_at=0
            self.generation+=1
            self.last_token=None
            self.invalidate("no_grid")
            self.state["source"]=self.input_source
            return self.snapshot()

    def reset_game(self):
        with self.lock:
            self.manual=False
            self.tracked_board=self.history=None
            self.tracked_orientation=None
            self.turn=None
            self.engine.request_reset()
            self.generation+=1
            self.last_token=None
            self.invalidate("paused" if self.settings["paused"] else "stabilizing")
            self.state.update(source=self.input_source,
                              orientation=None,history_complete=False,check=False)
            return self.snapshot()

    def calibrate(self, values):
        with self.lock:
            w,h=self.state.get("width",0),self.state.get("height",0)
            g=Grid(*(float(values[k]) for k in ("x0","y0","x1","y1")),w,h,"manual")
            if not g.valid():
                raise ValueError("请选择 9 列 10 行棋盘左上与右下的交叉点")
            self.grid=self.manual_grid=g
            self.generation+=1
            self.invalidate("stabilizing")
            return self.snapshot()

    def learn(self):
        with self.lock:
            if not self.frame or not self.grid:
                raise ValueError("请先显示并定位完整开局棋盘")
            image=cv2.imdecode(np.frombuffer(self.frame,np.uint8),cv2.IMREAD_COLOR)
            if not self.recognizer.learn(image,self.grid,self.settings["orientation"]):
                raise ValueError("学习需完整的 32 子开局，且棋子清晰可见")
            self.tracked_board=self.history=None
            self.turn=None
            self.generation+=1
            self.invalidate("stabilizing")
            return self.snapshot()

    def set_turn(self, values):
        turn=values.get("turn")
        if turn not in ("red","black"):
            raise ValueError("请选择红走或黑走")
        with self.lock:
            board=self.state.get("board")
            if board is None:
                raise ValueError("尚未识别到棋盘")
            validate(board)
            if in_check(board,opposite(turn)):
                raise ValueError("另一方处于被将军状态，请核对当前走子方")
            self.turn=turn
            self.tracked_board=copy.deepcopy(board)
            self.history={"fen":to_fen(board,turn),"moves":[],"complete":board==START_BOARD and turn=="red"}
            self.state.update(turn=turn,history_complete=self.history["complete"])
            self.generation+=1
            self.invalidate("stabilizing",clear_board=False)
            if self.manual:
                self._schedule()
            return self.snapshot()

    def set_fen(self, values):
        board,turn=parse_fen(str(values.get("fen","")))
        if in_check(board,opposite(turn)):
            raise ValueError("FEN 的走子方与被将军状态不一致")
        with self.lock:
            self.manual=True
            self.tracked_board=copy.deepcopy(board)
            self.turn=turn
            self.history={"fen":to_fen(board,turn),"moves":[],"complete":False}
            self.generation+=1
            self.invalidate("stabilizing",clear_board=False)
            self.state.update(board=board,turn=turn,position=validate(board),orientation="red_bottom",
                              source="manual_position",captured_at=None,history_complete=False)
            self.state["change_detected_at"]=time.time()
            self._schedule()
            return self.snapshot()

    def _track(self, board):
        if self.tracked_board is None:
            self.tracked_board=copy.deepcopy(board)
            if board==START_BOARD:
                self.turn="red"
                self.history={"fen":to_fen(board,"red"),"moves":[],"complete":True}
            else:
                self.turn=None
                self.history=None
            self.state["last_move"]=None
        elif board!=self.tracked_board:
            step=transition_path(self.tracked_board,board,self.turn)
            if step:
                moves,self.turn=step
                if self.history:
                    self.history["moves"].extend(moves)
                else:
                    self.history={"fen":to_fen(board,self.turn),"moves":[],"complete":False}
                self.state["last_move"]=moves[-1]
            elif board==START_BOARD:
                self.turn="red"
                self.history={"fen":to_fen(board,"red"),"moves":[],"complete":True}
                self.state["last_move"]=None
            else:
                self.turn=None
                self.history=None
                self.state["last_move"]=None
            self.tracked_board=copy.deepcopy(board)
        self.state.update(turn=self.turn,history_complete=bool(self.history and self.history["complete"]))

    def _schedule(self):
        board=self.state.get("board")
        if self.settings["paused"]:
            self.state.update(status="paused",suggestion=None)
            return
        if not self.turn:
            self.state.update(status="need_turn",suggestion=None)
            return
        if self.settings["my_color"] not in ("both",self.turn):
            self.state.update(status="opponent_turn",suggestion=None)
            return
        key=(str(board),self.turn,self.settings["budget_ms"],self.settings["my_color"])
        if key==self.analysis_key:
            return
        self.state.update(status="thinking",suggestion=None,error=None)
        if self.inflight is not None:
            return
        generation=self.generation
        self.inflight=generation
        cancel=threading.Event()
        self.analysis_cancel=cancel
        self.analysis_key=key
        settings=dict(self.settings)
        history=copy.deepcopy(self.history)
        threading.Thread(target=self._analyse,args=(copy.deepcopy(board),self.turn,settings,history,generation,cancel),daemon=True).start()

    def _analyse(self, board, turn, settings, history, generation, cancel):
        def publish(suggestion):
            with self.lock:
                if self.stop.is_set() or cancel.is_set() or self.generation!=generation:
                    return
                date=self.state.get("captured_at")
                if self.state["source"] in LIVE_SOURCES and (not date or time.time()-date>2):
                    self.invalidate("stale")
                    return
                suggestion["computed_at"]=time.time()
                suggestion["update_ms"]=round((time.time()-self.state.get("change_detected_at",time.time()))*1000,1)
                suggestion["generation"]=generation
                status="finished" if suggestion.get("finished") else "thinking" if suggestion.get("partial") else "ready"
                self.state.update(status=status,suggestion=suggestion)
        try:
            suggestion=self.engine.analyse(board,turn,settings["budget_ms"],history,on_update=publish,cancel=cancel)
            publish(suggestion)
        except SearchCancelled:
            pass
        except Exception as error:
            with self.lock:
                if not self.browser_capture:
                    with (self.session/"analysis-errors.jsonl").open("a", encoding="utf-8") as handle:
                        handle.write(json.dumps({"time":time.time(),"error":str(error),"board":board,"turn":turn},ensure_ascii=False)+"\n")
                if generation==self.generation:
                    self.state.update(status="error",error=str(error),suggestion=None)
        finally:
            with self.lock:
                if self.inflight==generation:
                    self.inflight=None
                if self.analysis_cancel is cancel:
                    self.analysis_cancel=None

    def observe(self, image, metadata, raw=b""):
        started=time.perf_counter()
        h,w=image.shape[:2]
        with self.lock:
            if self.browser_capture and not self.browser_capture.owns(metadata.get("capture_token")):
                return
            if self.manual:
                self._schedule()
                return
            self.frame=raw
            self.state.update({k:metadata.get(k) for k in ("captured_at","frame_id")})
            self.state.update(width=w,height=h)
            if self.settings["paused"]:
                self.invalidate("paused")
                return
            if self.grid and (self.grid.width!=w or self.grid.height!=h):
                self.grid=self.manual_grid=None
            if self.grid is None and time.monotonic()>=self.detect_at:
                self.detect_at=time.monotonic()+.8
                self.grid=detect_grid(image)
            if self.grid is None:
                self.invalidate("no_grid")
                return
            try:
                result=self.recognizer.read(image,self.grid,self.settings["orientation"])
            except ValueError:
                if self.manual_grid is None:
                    self.grid=None
                self.invalidate("no_grid")
                return
            board=result["board"]
            method="glyph_templates"
            direction=result["orientation"] or self.tracked_orientation or self.state.get("orientation")
            sides=result.get("display_sides")
            if self.tracked_board and sides and direction in ("red_bottom","black_bottom"):
                canonical=sides if direction=="red_bottom" else [row[::-1] for row in sides[::-1]]
                tracked=match_observation(self.tracked_board,canonical,self.turn)
                if tracked:
                    board=tracked[0]
                    result["orientation"]=direction
                    result["uncertain"]=[]
                    method="legal_move_tracking"
            self.state.update(board=board or result["display"],orientation=result["orientation"],
                              uncertain=result["uncertain"],confidence=result.get("confidence"),
                              recognition_method=method,
                              recognition_ms=round((time.perf_counter()-started)*1000,1))
            if result["needs_templates"]:
                self.invalidate("need_templates",clear_board=False)
                return
            if not board or result["uncertain"]:
                self.invalidate("uncertain",clear_board=False)
                return
            try:
                position=validate(board)
            except ValueError as error:
                self.invalidate("invalid_position",str(error),clear_board=False)
                return
            self.state["position"]=position
            key=str(board)
            if key!=self.seen_key:
                if self.analysis_cancel:
                    self.analysis_cancel.set()
                self.seen_key=key
                self.stable_count=1
                self.generation+=1
                self.analysis_key=None
                self.state.update(status="stabilizing",suggestion=None,error=None,turn=None,change_detected_at=time.time())
                return
            self.stable_count+=1
            if self.stable_count<2:
                return
            self._track(board)
            self.tracked_orientation=result["orientation"]
            if self.turn and in_check(board,opposite(self.turn)):
                self.turn=None
                self.history=None
                self.state["turn"]=None
            self.state["check"]=in_check(board,self.turn) if self.turn else False
            self._schedule()

    def reset_window_input(self, status, new_window=False):
        if new_window:
            self.reset_game()
            self.grid = self.manual_grid = None
            self.detect_at = 0
        self.frame = b""
        self.last_token = None
        self.state.update(captured_at=None, frame_id=None)
        if not self.manual:
            self.invalidate(status)

    def _load(self):
        if self.browser_capture:
            loaded, status = self.browser_capture.load(self.last_token)
            if status:
                self.reset_window_input(status)
            if loaded:
                frame, metadata, self.last_token = loaded
                return frame, metadata
            return None
        if self.image:
            data=self.image.read_bytes()
            return data,{"captured_at":None,"frame_id":str(self.image.stat().st_mtime_ns)}
        try:
            first=json.loads((self.session/"capture.json").read_text(encoding="utf-8"))
            if first.get("status")!="capturing":
                condition=first.get("status")
                if condition not in ("capture_starting","capture_unavailable","capture_no_frames",
                                     "multiple_devices","capture_error","capture_stopped"):
                    condition="waiting_capture"
                detail=first.get("message")
                error="USB 取屏失败："+detail[:500] if condition=="capture_error" and isinstance(detail,str) and detail else None
                self.invalidate(condition,error)
                # A prior frame must not hide the current capture fault as merely stale.
                self.state.update(captured_at=None,frame_id=None)
                self.frame=b""
                self.last_token=None
                return None
            if time.time()-first.get("captured_at",0)>2:
                self.invalidate("stale")
                return None
            token=(first["sequence"],first["captured_at"])
            if token==self.last_token:
                return None
            data=(self.session/"latest.jpg").read_bytes()
            if json.loads((self.session/"capture.json").read_text(encoding="utf-8"))!=first:
                return None
            self.last_token=token
            first["frame_id"]=f"{first['captured_at']:.6f}:{first['sequence']}"
            return data,first
        except (OSError,ValueError,KeyError):
            self.invalidate("waiting_capture")
            return None

    def run(self):
        cv2.setNumThreads(1)
        last_written=None
        while not self.stop.is_set():
            try:
                with self.lock:
                    if self.manual:
                        self._schedule()
                        loaded=None
                    else:
                        loaded=self._load()
                if loaded:
                    raw,metadata=loaded
                    image=cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR)
                    if image is None:
                        self.invalidate("error","无法解码手机画面")
                    else:
                        self.observe(image,metadata,raw)
                current=self.snapshot()
                key=(current["status"],current.get("frame_id"),self.generation,current.get("error"),
                     (current.get("suggestion") or {}).get("computed_at"))
                if not self.browser_capture and key!=last_written:
                    atomic_json(self.session/"latest-state.json",current)
                    last_written=key
            except Exception as error:
                self.invalidate("error",str(error))
            self.stop.wait(.08 if not self.image else .25)
        self.engine.close()
        self.invalidate("capture_stopped")
        if not self.browser_capture:
            atomic_json(self.session/"latest-state.json",self.snapshot())


def serve(observer, port):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_):
            pass

        def allowed(self):
            hosts=(f"127.0.0.1:{self.server.server_port}",f"localhost:{self.server.server_port}")
            return self.headers.get("Host") in hosts and self.headers.get("Origin") in (None,*("http://"+h for h in hosts))

        def send(self,status,data,mime="application/json"):
            if isinstance(data,dict):
                data=json.dumps(data,ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type",mime)
            self.send_header("Content-Length",str(len(data)))
            self.send_header("Cache-Control","no-store")
            self.send_header("X-Content-Type-Options","nosniff")
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError,ConnectionResetError):
                pass

        def do_GET(self):
            if not self.allowed():
                self.send(403,{"error":"不允许跨站访问"})
                return
            path=urlparse(self.path).path
            if path=="/":
                self.send(200,(ROOT/"index.html").read_bytes(),"text/html; charset=utf-8")
            elif path == "/browser_capture.js":
                self.send(200, (ROOT / "browser_capture.js").read_bytes(), "text/javascript; charset=utf-8")
            elif path == "/api/state":
                observer.ui_seen = time.monotonic()
                self.send(200,observer.snapshot())
            elif path=="/frame.jpg":
                with observer.lock:
                    data=observer.frame
                self.send(200 if data else 404,data,"image/jpeg")
            else:
                self.send(404,{"error":"未找到"})

        def do_POST(self):
            if not self.allowed():
                self.send(403,{"error":"不允许跨站访问"})
                return
            path = urlparse(self.path).path
            if handle_capture(self, observer, path):
                return
            try:
                count=int(self.headers.get("Content-Length","0"))
                if not 0<count<=16384 or not self.headers.get("Content-Type","").startswith("application/json"):
                    raise ValueError("请求格式错误")
                values=json.loads(self.rfile.read(count))
                if not isinstance(values,dict):
                    raise ValueError("请求格式错误")
                if path=="/api/settings":
                    state=observer.configure(values)
                elif path=="/api/calibrate":
                    state=observer.calibrate(values)
                elif path=="/api/reset-grid":
                    state=observer.reset_grid()
                elif path=="/api/reset-game":
                    state=observer.reset_game()
                elif path=="/api/learn":
                    state=observer.learn()
                elif path=="/api/turn":
                    state=observer.set_turn(values)
                elif path=="/api/fen":
                    state=observer.set_fen(values)
                elif path=="/api/stop":
                    observer.stop.set()
                    observer.invalidate("capture_stopped")
                    state=observer.snapshot()
                else:
                    self.send(404,{"error":"未找到"})
                    return
                self.send(200,state)
            except (ValueError,TypeError,KeyError,OverflowError) as error:
                self.send(400,{"error":str(error)})
    return ThreadingHTTPServer(("127.0.0.1",port),Handler)


def main():
    parser = argparse.ArgumentParser()
    windows = os.name == "nt"
    default_dir = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData/Local")) / "XiangqiAssistant" if windows else ROOT / ".runtime"
    parser.add_argument("--browser-capture", action=argparse.BooleanOptionalAction, default=windows)
    parser.add_argument("--open-browser", action=argparse.BooleanOptionalAction, default=windows and getattr(sys, "frozen", False))
    parser.add_argument("--ready-file", type=Path)
    parser.add_argument("--port",type=int,default=0 if windows else 8767)
    parser.add_argument("--session",default=str(default_dir))
    parser.add_argument("--image")
    parser.add_argument("--device")
    parser.add_argument("--duration",type=float,default=86400)
    parser.add_argument("--parent-pid",type=int)
    args=parser.parse_args()
    observer=Observer(args.session,args.image,browser_capture=args.browser_capture)
    server=serve(observer,args.port)
    capture=None
    capture_log=None
    if not args.image and not observer.browser_capture:
        capture_log=(observer.session/"capture.log").open("a", encoding="utf-8")
        command=[str(ROOT/"bin/phone-capture"),"--output",str(observer.session),"--duration",str(args.duration)]
        if args.device:
            command += ["--device",args.device]
        capture=subprocess.Popen(command,stdout=capture_log,stderr=subprocess.STDOUT)
    observer.ui_seen = time.monotonic()
    worker=threading.Thread(target=observer.run,daemon=True)
    worker.start()
    threading.Thread(target=server.serve_forever,daemon=True).start()
    ready = {"url": f"http://127.0.0.1:{server.server_port}", "source": observer.state["source"],
             "backend_pid": os.getpid(), "capture_pid": capture.pid if capture else None}
    if args.ready_file:
        atomic_json(args.ready_file, ready)
    if sys.stdout is not None:
        print(json.dumps(ready), flush=True)
    if args.open_browser:
        webbrowser.open(ready["url"])
    for signum in (signal.SIGINT,signal.SIGTERM):
        signal.signal(signum,lambda *_:observer.stop.set())
    try:
        deadline=time.monotonic()+args.duration
        while not observer.stop.wait(min(1,max(0,deadline-time.monotonic()))):
            if time.monotonic()>=deadline or (args.parent_pid and os.getppid()!=args.parent_pid):
                break
            if args.open_browser and time.monotonic() - observer.ui_seen > 120:
                break
    finally:
        observer.stop.set()
        if capture:
            capture.terminate()
            try:
                capture.wait(timeout=8)
            except subprocess.TimeoutExpired:
                capture.kill()
                capture.wait()
        worker.join(timeout=12)
        server.shutdown()
        server.server_close()
        if capture_log:
            capture_log.close()


if __name__=="__main__":
    main()

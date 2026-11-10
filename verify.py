"""Run behavioural checks; optional generated fixtures are deliberately labelled synthetic."""
import argparse
import json
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
import cv2
import numpy as np
import copy
from app import Observer, serve
from engine import Engine, SearchCancelled
from rules import START_BOARD, START_FEN, apply_move, color, in_check, legal_moves, notation, opposite, parse_fen, to_fen, transition, transition_path, match_observation, validate
from vision import Recognizer, Grid, detect_grid

ROOT=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--fixtures",type=Path)
    parser.add_argument("--report",type=Path,default=ROOT/"validation/checks.json")
    args=parser.parse_args()
    checks={}
    assert len(legal_moves(START_BOARD,"red"))==44
    assert notation(START_BOARD,"h2e2")=="炮二平五"
    assert notation(START_BOARD,"h0g2")=="马二进三"
    assert notation(START_BOARD,"h9g7")=="马8进7"
    after=apply_move(START_BOARD,"h2e2")
    assert transition(START_BOARD,after,"red")==("h2e2","black")
    assert transition(START_BOARD,after,"black") is None
    checks["coordinates_notation_and_transition"]=True
    replied=apply_move(after,"b9c7")
    assert transition_path(START_BOARD,replied,"red")==(["h2e2","b9c7"],"red")
    assert transition_path(START_BOARD,replied,None) is None
    assert transition_path(START_BOARD,apply_move(replied,"h0g2"),"red") is None
    checks["unique_two_ply_reply_and_unknown_turn"]=True
    ambiguous=[[""]*9 for _ in range(10)]
    ambiguous[0][4]="k";ambiguous[9][4]="K";ambiguous[3][4]="P";ambiguous[7][4]="N"
    for col in (3,4,5):
        ambiguous[5][col]="p"
    validate(ambiguous)
    assert "e2d4" in legal_moves(ambiguous,"red") and "e2f4" in legal_moves(ambiguous,"red")
    assert "e4d4" in legal_moves(apply_move(ambiguous,"e2d4"),"black")
    assert "e4f4" in legal_moves(apply_move(ambiguous,"e2f4"),"black")
    left=apply_move(apply_move(ambiguous,"e2d4"),"e4d4")
    right=apply_move(apply_move(ambiguous,"e2f4"),"e4f4")
    assert left==right and transition_path(ambiguous,left,"red") is None
    checks["ambiguous_capture_history_requires_confirmation"]=True
    sides=lambda board:[[color(p) or "" for p in row] for row in board]
    assert match_observation(START_BOARD,sides(replied),"red")== (replied,["h2e2","b9c7"],"red")
    assert match_observation(ambiguous,sides(left),"red") is None
    unknown=sides(replied);unknown[2][2]="?"
    assert match_observation(START_BOARD,unknown,"red") is None
    assert match_observation(START_BOARD,sides(apply_move(replied,"h0g2")),"red") is None
    checks["legal_color_tracking_unknown_and_ambiguous_rejected"]=True
    with tempfile.TemporaryDirectory() as temporary:
        observer=Observer(temporary)
        observer.settings["my_color"]="black"
        observer.grid=Grid(40,40,360,400,450,450)
        observer._track(START_BOARD)
        observer.state["orientation"]="red_bottom"
        observer.tracked_orientation="red_bottom"
        damaged=copy.deepcopy(replied);damaged[0][6]="n";damaged[9][4]="?"
        result={"board":None,"display":damaged,"display_sides":sides(replied),"orientation":None,
                "uncertain":[[4,9]],"needs_templates":False,"confidence":.8}
        observer.recognizer.read=lambda *_:copy.deepcopy(result)
        image=np.zeros((450,450,3),np.uint8)
        broken=copy.deepcopy(result);broken["display_sides"][0][0]="?"
        observer.recognizer.read=lambda *_:copy.deepcopy(broken)
        observer.observe(image,{"captured_at":None,"frame_id":"unknown"})
        assert observer.state["status"]=="uncertain"
        observer.recognizer.read=lambda *_:copy.deepcopy(result)
        for i in range(2):
            observer.observe(image,{"captured_at":None,"frame_id":str(i)})
        assert observer.state["board"]==replied
        assert observer.turn=="red" and observer.history["moves"]==["h2e2","b9c7"]
        assert not observer.state["uncertain"] and observer.state["recognition_method"]=="legal_move_tracking"
        observer.engine.close()
        checks["static_piece_identity_survives_glyph_noise"]=True
    blocked=[r[:] for r in START_BOARD]
    blocked[8][7]="P";blocked[6][8]=""
    assert "h0g2" not in legal_moves(blocked,"red")
    cannon=[r[:] for r in START_BOARD]
    assert "b2b9" in legal_moves(cannon,"red")
    cannon[2][1]=""
    assert "b2b9" not in legal_moves(cannon,"red")
    assert "e0f0" not in legal_moves(START_BOARD,"red")
    checks["horse_leg_cannon_screen_and_own_pieces"]=True
    bare=[[""]*9 for _ in range(10)]
    bare[0][4]="k";bare[9][4]="K"
    assert in_check(bare,"red") and in_check(bare,"black")
    try:
        validate(bare)
        raise AssertionError("facing kings accepted")
    except ValueError:
        pass
    checks["facing_kings_rejected"]=True
    engine=Engine()
    commands=[]
    write=engine._write
    def record_write(command):
        commands.append(command)
        write(command)
    engine._write=record_write
    try:
        assert engine.perft_moves(START_BOARD,"red")==sorted(legal_moves(START_BOARD,"red"))
        result=engine.analyse(after,"black",250)
        assert result["move"] in legal_moves(after,"black")
        checks["official_engine_start_and_black_search"]={"start_legal_moves":44,"move":result["move"],"text":result["text"],"engine_ms":result["engine_ms"]}
        updates=[]
        history={"fen":START_FEN,"moves":[],"complete":True}
        result=engine.analyse(START_BOARD,"red",1000,history,on_update=updates.append)
        assert updates and all(p["partial"] and p["move"] in legal_moves(START_BOARD,"red") for p in updates)
        assert all(p["engine_ms"]<result["engine_ms"] for p in updates)
        assert not result["cache_reused"] and not result["partial"]
        assert result["continuation"] and result["continuation"][0]["move"]==result["move"]
        next_history={"fen":START_FEN,"moves":["h2e2","b9c7"],"complete":True}
        resets=commands.count("ucinewgame")
        result=engine.analyse(replied,"red",250,next_history)
        assert result["cache_reused"] and result["move"] in legal_moves(replied,"red")
        assert commands.count("ucinewgame")==resets
        engine.request_reset()
        result=engine.analyse(replied,"red",250,next_history)
        assert not result["cache_reused"]
        assert commands.count("ucinewgame")==resets+1
        checks["progressive_legal_suggestions_and_game_cache"]={"updates":len(updates),"history_extension_reuses_cache":True,"manual_reset_clears_cache":True}
        cancelled,started=threading.Event(),threading.Event()
        errors=[]
        def long_search():
            try:
                engine.analyse(replied,"red",30000,next_history,on_update=lambda _:started.set(),cancel=cancelled)
                errors.append("cancelled search completed")
            except SearchCancelled:
                pass
            except Exception as error:
                errors.append(str(error))
        worker=threading.Thread(target=long_search)
        worker.start();assert started.wait(5)
        cancel_at=time.monotonic();cancelled.set();worker.join(3)
        assert not worker.is_alive() and not errors,errors
        cancel_ms=round((time.monotonic()-cancel_at)*1000,1)
        result=engine.analyse(after,"black",250)
        assert result["move"] in legal_moves(after,"black")
        checks["long_search_cancellation_drains_uci_before_next_position"]={"cancel_ms":cancel_ms,"next_move":result["move"]}
    finally:
        engine.close()
    with tempfile.TemporaryDirectory() as temporary:
        observer=Observer(temporary)
        observer._track(START_BOARD)
        assert observer.turn=="red" and observer.history["complete"]
        observer._track(replied)
        assert observer.turn=="red" and observer.history["moves"]==["h2e2","b9c7"]
        assert observer.history["complete"]
        observer._track(START_BOARD)
        earlier=["h2e2","b9c7","e2h2","c7b9"]
        assert observer.history["moves"]==earlier
        board=START_BOARD
        loop=["b0c2","b9c7","c2b0","c7b9"]
        for move in loop:
            board=apply_move(board,move);observer._track(board)
        assert board==START_BOARD and observer.history["moves"]==earlier+loop
        observer._track(board)
        assert observer.history["moves"]==earlier+loop
        checks["repetition_history_preserved_at_opening"]=True
        observer.configure({"my_color":"black","budget_ms":2000})
        restarted=Observer(temporary)
        assert restarted.settings["my_color"]=="black" and restarted.settings["budget_ms"]==2000
        observer.engine.close();restarted.engine.close()
        checks["settings_restore"]=True
    with tempfile.TemporaryDirectory() as temporary:
        observer=Observer(temporary)
        observer.settings.update(my_color="black",budget_ms=30000,paused=True)
        observer.grid=observer.manual_grid=Grid(40,40,360,400,450,450,"manual")
        observer.recognizer.templates={name:np.zeros((30,30),np.uint8) for name in "RNBAKCPrnbakcp"}
        templates=observer.recognizer.templates
        grid=observer.grid
        observer._track(replied)
        observer.manual=True
        observer.state.update(source="manual_position",board=replied,suggestion={"move":"h0g2"},status="ready")
        observer.history={"fen":START_FEN,"moves":["h2e2","b9c7"],"complete":True}
        observer.analysis_cancel=threading.Event()
        cancel=observer.analysis_cancel
        before=dict(observer.settings)
        server=serve(observer,0)
        worker=threading.Thread(target=server.serve_forever,daemon=True)
        worker.start()
        url=f"http://127.0.0.1:{server.server_port}"
        try:
            request=urllib.request.Request(url+"/api/reset-game",data=b"{}",headers={"Content-Type":"application/json"},method="POST")
            with urllib.request.urlopen(request,timeout=3) as response:
                state=json.load(response)
            assert state["status"]=="paused" and state["source"]=="live_usb_screen"
            assert state["suggestion"] is None and state["board"] is None and not state["history_complete"]
            assert cancel.is_set() and observer.engine.reset_requested.is_set()
            assert observer.settings==before and observer.grid is grid and observer.manual_grid is grid
            assert observer.recognizer.templates is templates and not observer.manual
            assert observer.history is None and observer.tracked_board is None and observer.turn is None
            observer.settings["paused"]=False
            observer.recognizer.read=lambda *_:{"board":copy.deepcopy(START_BOARD),"display":copy.deepcopy(START_BOARD),
                "orientation":"red_bottom","uncertain":[],"needs_templates":False,"confidence":1.}
            image=np.zeros((450,450,3),np.uint8)
            for i in range(2):
                observer.observe(image,{"captured_at":time.time(),"frame_id":str(i)})
            assert observer.state["status"]=="opponent_turn" and observer.state["board"]==START_BOARD
            assert observer.turn=="red" and observer.history["complete"] and observer.history["moves"]==[]
            checks["manual_reset_api_preserves_settings_templates_grid_and_resumes_auto"]=True
        finally:
            server.shutdown();server.server_close();worker.join(3);observer.engine.close()
    with tempfile.TemporaryDirectory() as temporary:
        observer=Observer(temporary)
        observer.state.update(board=START_BOARD,position=validate(START_BOARD),captured_at=time.time()-3,
                              status="ready",suggestion={"move":"h2e2"},turn="red")
        snapshot=observer.snapshot()
        assert snapshot["status"]=="stale" and snapshot["suggestion"] is None and snapshot["board"] is None
        observer.engine.close()
        checks["stale_capture_clears_suggestion"]=True
    with tempfile.TemporaryDirectory() as temporary:
        observer=Observer(temporary)
        for condition in ("capture_starting","capture_unavailable","capture_no_frames","multiple_devices","capture_error"):
            observer.state.update(board=START_BOARD,captured_at=time.time()-5,frame_id="old",
                                  status="ready",suggestion={"move":"h2e2"},turn="red")
            observer.frame=b"old image"
            (Path(temporary)/"capture.json").write_text(json.dumps({"status":condition,"message":"stream failed"}))
            assert observer._load() is None
            snapshot=observer.snapshot()
            assert snapshot["status"]==condition and snapshot["suggestion"] is None and snapshot["board"] is None
            assert snapshot["frame_id"] is None and snapshot["captured_at"] is None and observer.frame==b""
            assert snapshot["message"]!="等待 iPhone USB 屏幕"
        assert "stream failed" in snapshot["message"]
        observer.engine.close()
        checks["usb_source_failure_reports_condition_and_clears_old_frame"]=True
    with tempfile.TemporaryDirectory() as temporary:
        observer=Observer(temporary)
        started,release=threading.Event(),threading.Event()
        class DelayedEngine:
            def analyse(self,*_,on_update=None,cancel=None):
                on_update({"move":"h2e2","partial":True})
                started.set();assert release.wait(3)
                on_update({"move":"h2e2","partial":True})
                return {"move":"h2e2"}
            def close(self):
                pass
        observer.engine.close();observer.engine=DelayedEngine()
        observer.state.update(board=START_BOARD,turn="red",source="manual_position",change_detected_at=time.time())
        observer.turn="red"
        observer._schedule();assert started.wait(3)
        assert observer.state["status"]=="thinking" and observer.state["suggestion"]["partial"]
        observer.invalidate("uncertain")
        release.set()
        deadline=time.monotonic()+3
        while observer.inflight is not None and time.monotonic()<deadline:
            time.sleep(.01)
        assert observer.state["suggestion"] is None and observer.state["status"]=="uncertain"
        checks["old_async_result_and_intermediate_update_discarded"]=True
    if args.fixtures:
        fixtures=args.fixtures
        expected=json.loads((fixtures/"expected.json").read_text())
        recognition=[]
        with tempfile.TemporaryDirectory() as temporary:
            recognizer=Recognizer(Path(temporary)/"templates.npz")
            for name,target in (("start","start"),("red-moved","red-moved"),("black-moved","black-moved"),
                                ("start-flipped","start"),("midgame-flipped","black-moved")):
                image=cv2.imread(str(fixtures/(name+".jpg")))
                grid=detect_grid(image)
                assert grid is not None,name
                result=recognizer.read(image,grid)
                assert result["board"]==expected[target],name
                assert not result["uncertain"],name
                recognition.append({"input":name,"all_90_cells_match":True,"orientation":result["orientation"]})
            blank=image.copy();blank[:]=(235,235,235)
            assert detect_grid(blank) is None
            checks["synthetic_vision_fixtures"]=recognition
            checks["non_board_page_rejected"]=True
    report={"passed":True,"checks":checks,"scope":"Rules, observer state, engine and optional synthetic images; physical captures are checked separately.",
            "fixture_provenance":"Synthetic labelled boards; no claim of accuracy on an untested game skin."}
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(report,ensure_ascii=False))


if __name__=="__main__":
    main()

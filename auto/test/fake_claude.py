#!/usr/bin/env python3
"""A stand-in for `claude --print`, for testing the driver without spending anything.

It keeps a size for each session in $FAKE_STATE, grows it on every call, compacts
at $FAKE_LIMIT, and prints stream events shaped like Claude Code's.
"""
import json
import os
import sys
import uuid

args = sys.argv[1:]
prompt = args[args.index("--print") + 1]
state_file = os.path.join(os.environ["FAKE_STATE"], "sessions.json")
limit = int(os.environ.get("FAKE_LIMIT", "300000"))
grow = int(os.environ.get("FAKE_GROW", "40000"))
store = json.load(open(state_file)) if os.path.exists(state_file) else {"sizes": {}, "util": 0.10}

if "--session-id" in args:
    session = args[args.index("--session-id") + 1]
    store["sizes"][session] = 12000
else:
    source = args[args.index("--resume") + 1]
    if source not in store["sizes"]:
        print("No conversation found with session ID: " + source, file=sys.stderr)
        sys.exit(1)
    if "--fork-session" in args:
        session = str(uuid.uuid4())
        store["sizes"][session] = store["sizes"][source]
    else:
        session = source


def emit(row):
    print(json.dumps(row), flush=True)


emit({"type": "system", "subtype": "init", "session_id": session,
      "claude_code_version": os.environ.get("FAKE_VERSION", "9.9.9"), "apiKeySource": "none"})
if os.environ.get("FAKE_FAIL_ON") and os.environ["FAKE_FAIL_ON"] in prompt:
    emit({"type": "result", "subtype": "error_during_execution", "is_error": True,
          "result": "boom", "session_id": session})
    sys.exit(1)
size = store["sizes"][session]
if os.environ.get("FAKE_BREAK_ON") and os.environ["FAKE_BREAK_ON"] in prompt:
    size += 5000
    emit({"type": "assistant", "parent_tool_use_id": None, "session_id": session, "message": {
        "usage": {"input_tokens": 10, "cache_read_input_tokens": size, "cache_creation_input_tokens": 0}}})
    emit({"type": "result", "subtype": "error_during_execution", "is_error": True,
          "result": "usage limit reached", "session_id": session})
    store["sizes"][session] = size
    json.dump(store, open(state_file, "w"))
    sys.exit(1)
events = []
if prompt.strip() == "/compact":
    events.append(("manual", size))
    size = 30000
else:
    quiz = prompt.startswith("Answer each numbered question")
    small = quiz or prompt.startswith(("Noted.", "Please carry on"))
    size += 800 if small else grow
    if size > limit:
        events.append(("auto", size))
        size = 35000
for trigger, before in events:
    emit({"type": "system", "subtype": "status", "status": "compacting", "session_id": session})
    emit({"type": "system", "subtype": "compact_boundary", "session_id": session,
          "compact_metadata": {"trigger": trigger, "pre_tokens": before, "post_tokens": size,
                               "duration_ms": 1234, "preserved_segment": {"x": 1}}})
emit({"type": "assistant", "parent_tool_use_id": None, "session_id": session, "message": {
    "usage": {"input_tokens": 10, "cache_read_input_tokens": size - 2010,
              "cache_creation_input_tokens": 2000, "output_tokens": 50}}})
store["util"] = round(store["util"] + float(os.environ.get("FAKE_UTIL_STEP", "0.004")), 4)
emit({"type": "rate_limit_event", "rate_limit_info": {"status": "allowed", "unifiedWindows": {
    "seven_day": {"utilization": round(store["util"], 2), "status": "allowed"}}}})
emit({"type": "result", "subtype": "success", "is_error": False, "session_id": session,
      "total_cost_usd": 0.01, "permission_denials": [], "result": "reply to: " + prompt[:40]})
store["sizes"][session] = size
json.dump(store, open(state_file, "w"))

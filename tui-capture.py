#!/usr/bin/env python3
"""tui-capture.py

Runs one interactive Claude Code session in a pseudo-terminal, types a
scripted list of prompts into it, and records everything the terminal was
sent. Nobody has to sit at the keyboard.

    python3 tui-capture.py <steps.json> <working directory> <output directory>

It writes two files into the output directory:

    session.cast   an asciicast v2 recording: every byte Claude Code wrote
                   to the terminal, with a marker at the end of each step
    session.log    what this script did, step by step

It writes nowhere else. Claude Code keeps its own records of the session,
as it does for any session. Python 3 standard library only.

steps.json holds the terminal size, the command to start, and the steps:

    {"cols": 100, "rows": 50, "command": ["claude", "..."],
     "steps": [{"label": "rules", "type": "Five rules ..."},
               {"label": "trust", "if_seen": "trust", "keys": "\\r"}]}

A step types its text and presses Enter, then waits until the terminal has
been quiet for a few seconds. A step with "if_seen" runs only if that word
appeared on the terminal since the previous step. A step with "expect"
presses its keys, checks that the terminal then shows the expected text,
and only then presses "confirm_keys"; if the text is not there it presses
"abort_keys" and stops the recording.
"""

import codecs
import fcntl
import json
import os
import pty
import re
import select
import signal
import struct
import sys
import termios
import time

# Variables Claude Code sets in the shells it starts. The recorded session is
# started without them, so it begins the way it would from a plain terminal.
PARENT_SESSION_VARIABLES = (
    "CLAUDECODE CLAUDE_CODE_CHILD_SESSION CLAUDE_CODE_SESSION_ID "
    "CLAUDE_CODE_ENTRYPOINT CLAUDE_CODE_EXECPATH CLAUDE_CODE_BRIDGE_SESSION_ID "
    "CLAUDE_CODE_MESSAGING_SOCKET CLAUDE_CODE_MESSAGING_TOKEN CLAUDE_EFFORT "
    "CLAUDE_PID CLAUDE_JOB_DIR AI_AGENT"
).split()

ESCAPES = re.compile(
    r"\x1b\[[0-9;?<=>!]*[ -/]*[@-~]"          # CSI sequences
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"     # OSC sequences
    r"|\x1b[()][0-9A-Za-z]|\x1b[=>78DEHMNOZc]"
)



def plain_gap(match):
    """Escape sequences vanish from the plain text, except the ones that move
    the cursor along a line: programs use those in place of spaces."""
    sequence = match.group(0)
    return " " if sequence.startswith("\x1b[") and sequence[-1] in "GC" else ""


# Questions a program may put to the terminal. A real terminal answers them;
# with nobody answering, a program can wait. Two kinds get the answer a
# plain terminal would give. Anything else asked is written to the log.
DEVICE_ATTRIBUTES = re.compile(rb"\x1b\[0?c")
COLOUR_QUERY = re.compile(rb"\x1b\](1[01]);\?(?:\x07|\x1b\\)")
OTHER_QUERIES = re.compile(rb"\x1b\[6n|\x1b\[\?u|\x1b\[>0?q|\x1b\[>0?c|\x1b\[\?[0-9;]+\$p")


class Session:
    def __init__(self, command, cwd, cols, rows, out_dir):
        self.command = command
        self.cwd = cwd
        self.cols = cols
        self.rows = rows
        self.cast = open(os.path.join(out_dir, "session.cast"), "w", encoding="utf-8")
        self.log_file = open(os.path.join(out_dir, "session.log"), "w", encoding="utf-8")
        self.decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.started = time.time()
        self.last_output = self.started
        self.since_step = ""      # plain text seen since the previous step
        self.carry = b""          # tail of the last chunk, for split queries
        self.closed = False
        self.pid = None
        self.fd = None
        self.total_bytes = 0

    # -- records ----------------------------------------------------------
    def now(self):
        return round(time.time() - self.started, 3)

    def log(self, message):
        self.log_file.write("%8.2f  %s\n" % (self.now(), message))
        self.log_file.flush()

    def event(self, kind, data):
        self.cast.write(json.dumps([self.now(), kind, data], ensure_ascii=False) + "\n")
        self.cast.flush()

    def mark(self, label):
        self.event("m", label)
        self.log("mark %s" % label)

    # -- the child process ------------------------------------------------
    def spawn(self):
        environment = dict(os.environ)
        removed = [name for name in PARENT_SESSION_VARIABLES if name in environment]
        for name in removed:
            del environment[name]
        environment["TERM"] = "xterm-256color"
        environment["COLORTERM"] = "truecolor"
        for name in ("COLUMNS", "LINES", "NO_COLOR", "FORCE_COLOR"):
            environment.pop(name, None)
        size = struct.pack("HHHH", self.rows, self.cols, 0, 0)
        header = {"version": 2, "width": self.cols, "height": self.rows,
                  "timestamp": int(self.started),
                  "env": {"TERM": "xterm-256color", "SHELL": environment.get("SHELL", "")},
                  "command": " ".join(self.command)}
        self.cast.write(json.dumps(header) + "\n")
        self.log("start: %s" % " ".join(self.command))
        self.log("in: %s" % self.cwd)
        self.log("terminal: %d columns by %d rows" % (self.cols, self.rows))
        self.log("parent session variables removed: %s" % (" ".join(removed) or "none"))
        pid, fd = pty.fork()
        if pid == 0:
            try:
                fcntl.ioctl(0, termios.TIOCSWINSZ, size)
                os.chdir(self.cwd)
                os.execvpe(self.command[0], self.command, environment)
            finally:
                os._exit(127)
        self.pid, self.fd = pid, fd
        fcntl.ioctl(fd, termios.TIOCSWINSZ, size)

    def answer_queries(self, chunk):
        window = self.carry + chunk
        offset = len(self.carry)
        for match in DEVICE_ATTRIBUTES.finditer(window):
            if match.end() > offset:
                os.write(self.fd, b"\x1b[?1;2c")
                self.log("answered a device-attributes query")
        for match in COLOUR_QUERY.finditer(window):
            if match.end() > offset:
                which = match.group(1)
                colour = b"rgb:e6e6/e6e6/e6e6" if which == b"10" else b"rgb:1a1a/1a1a/1a1a"
                os.write(self.fd, b"\x1b]" + which + b";" + colour + b"\x1b\\")
                self.log("answered a colour query (%s)" % which.decode())
        for match in OTHER_QUERIES.finditer(window):
            if match.end() > offset:
                self.log("left unanswered: %r" % match.group(0))
        self.carry = window[-24:]

    def pump(self, timeout):
        """Read what the terminal was sent, once. Returns the byte count."""
        if self.closed:
            time.sleep(min(timeout, 0.2))
            return 0
        readable, _, _ = select.select([self.fd], [], [], timeout)
        if not readable:
            return 0
        try:
            chunk = os.read(self.fd, 65536)
        except OSError:
            chunk = b""
        if not chunk:
            self.closed = True
            self.log("the session closed its terminal")
            return 0
        self.total_bytes += len(chunk)
        self.last_output = time.time()
        text = self.decoder.decode(chunk)
        if text:
            self.event("o", text)
            self.since_step += ESCAPES.sub(plain_gap, text)
            if len(self.since_step) > 400000:
                self.since_step = self.since_step[-200000:]
        self.answer_queries(chunk)
        return len(chunk)

    def wait_quiet(self, least, quiet, most):
        """Wait until nothing has been written for `quiet` seconds."""
        began = time.time()
        while not self.closed:
            self.pump(0.25)
            now = time.time()
            if now - began >= least and now - self.last_output >= quiet:
                return True
            if now - began >= most:
                self.log("still busy after %d seconds; moving on" % most)
                return False
        return True

    def send(self, data):
        if self.closed:
            return
        os.write(self.fd, data)

    def type_text(self, text):
        # One character at a time, the way a keyboard sends them. A long
        # burst can be taken for a paste.
        for character in text:
            self.send(character.encode("utf-8"))
            self.pump(0.004)

    def stop(self):
        if self.pid is None:
            return
        deadline = time.time() + 12
        while not self.closed and time.time() < deadline:
            self.pump(0.25)
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                finished, _ = os.waitpid(self.pid, os.WNOHANG)
            except ChildProcessError:
                finished = self.pid
            if finished:
                break
            try:
                os.kill(self.pid, sig)
            except ProcessLookupError:
                break
            time.sleep(2)
        self.log("done: %d bytes recorded" % self.total_bytes)
        self.cast.close()
        self.log_file.close()


def main():
    if len(sys.argv) != 4:
        sys.stderr.write(__doc__)
        return 2
    plan = json.load(open(sys.argv[1], encoding="utf-8"))
    cwd = os.path.abspath(os.path.expanduser(sys.argv[2]))
    out_dir = os.path.abspath(os.path.expanduser(sys.argv[3]))
    os.makedirs(out_dir, exist_ok=True)
    session = Session(plan["command"], cwd, int(plan.get("cols", 100)),
                      int(plan.get("rows", 50)), out_dir)
    overall_limit = float(plan.get("overall_limit_seconds", 1500))

    def give_up(signum, frame):
        session.log("stopped by signal %d" % signum)
        session.closed = True
    signal.signal(signal.SIGTERM, give_up)
    signal.signal(signal.SIGINT, give_up)

    session.spawn()
    session.wait_quiet(float(plan.get("startup_least", 3)), float(plan.get("startup_quiet", 3)),
                       float(plan.get("startup_most", 45)))
    session.mark("started")

    for step in plan["steps"]:
        if session.closed:
            session.log("the session has ended; skipping %s" % step["label"])
            continue
        if time.time() - session.started > overall_limit:
            session.log("past the overall limit; skipping %s" % step["label"])
            continue
        wanted = step.get("if_seen")
        if wanted and not re.search(wanted, session.since_step, re.IGNORECASE):
            session.log("skip %s: %r was not on the terminal" % (step["label"], wanted))
            continue
        session.log("step %s" % step["label"])
        session.since_step = ""
        if step.get("type"):
            session.type_text(step["type"])
            session.wait_quiet(0.6, 0.5, 4)
            if step.get("mark_typed"):
                session.mark(step["label"] + "-typed")
        keys = step.get("keys")
        if keys is None and step.get("enter", True):
            keys = "\r"
        if keys:
            session.send(keys.encode("utf-8"))
        expect = step.get("expect")
        if expect:
            # A two-part step: press the keys, check the terminal shows what
            # is expected, and only then confirm. Otherwise back out and stop.
            session.wait_quiet(1.0, 1.0, 8)
            if re.search(expect, session.since_step):
                session.log("saw %r; confirming" % expect)
                session.send(step.get("confirm_keys", "\r").encode("utf-8"))
            else:
                session.log("did not see %r; backing out and stopping" % expect)
                session.send(step.get("abort_keys", "\x1b").encode("utf-8"))
                session.wait_quiet(1, 1, 5)
                session.mark(step["label"] + "-refused")
                break
        session.wait_quiet(float(step.get("least", 3)), float(step.get("quiet", 5)),
                           float(step.get("most", 240)))
        session.mark(step["label"])

    session.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

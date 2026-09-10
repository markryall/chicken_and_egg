#!/usr/bin/env python3
"""
Run a markdown document as an interactive, resumable runbook.

The idea is that the documentation *is* the program. Prose explains each step,
fenced blocks say what to run, and an annotation says how to tell whether the
step is already done. There is no second artifact to drift out of sync.

  ./runbook.py <file.md>             # step through whatever is not done
  ./runbook.py <file.md> --list      # print the board and exit
  ./runbook.py <file.md> --check     # unfinished step ids; exit 1 if any
  ./runbook.py <file.md> --ask       # list saved answers
  ./runbook.py <file.md> --ask <id>  # change one answer
  ./runbook.py <file.md> --reset     # forget skips and answers

Format
------

  # Title of the runbook          <- h1, once
  ## Phase name                   <- groups steps on the board
  ### Step title                  <- one step
  prose...                        <- shown when the step comes up
  ```bash {id=x check="..."}      <- what to run
  ```

Block languages: `bash`/`sh` run a command, `manual` prints instructions for a
human and waits, `ask` puts a question and remembers the answer, `runbook`
hands over to another runbook. Attributes:

  id=slug          required; identifies the step in the state file
  check="cmd"      exit 0 means already done. Without it a step can only be
                   marked done by running it, and will not be re-detected
  kind=interactive hands the terminal over rather than capturing output
  needs=a,b        wait until those step ids are done
  capture=name     the step's last line of output becomes the answer `name`,
                   so paths can be discovered rather than written down twice
  default="x"      ask blocks only; offered when the answer is left empty.
                   $VAR here is read from the environment, so a launcher can
                   pre-fill an answer without editing the document
  secret=true      ask blocks only; no echo, and deliberately not persisted

Answers reach every later command as an environment variable named after the
id — `id=github-user` becomes `$GITHUB_USER` in both `check` and the body, so a
runbook is asked once and personalised on every run after that.

Where commands run
------------------

In the repo holding the document — the nearest parent of the file with a
`.git`, `.jj` or `.hg` in it, or the file's own directory if it is not a
checkout. So a runbook says `./setup-fish.sh` and `--file Brewfile`, and stays
right whether the machine cloned it to ~/code, ~/src or a scratch directory.
`$RUNBOOK_ROOT` holds that directory for the few commands that need an
absolute path anyway, such as the target of a symlink.

Why a check rather than a log of what ran
-----------------------------------------

Every runbook tool tracks whether *it* performed a step. That is a journal, and
a journal is empty on a machine that was set up by someone else, or by hand
last Tuesday. A check asks the machine instead, so a runbook run against a
half-configured laptop opens on the truth rather than marching through forty
steps that were already done. It also makes quitting free: interrupt anything,
re-run, and the board re-derives itself.
"""

import json
import os
import re
import subprocess
import sys

STATE_DIR = os.path.expanduser("~/.local/state/runbook")

# Every command runs here rather than wherever you happened to be standing.
# Set from the document at startup; see runbook_root.
ROOT = os.getcwd()

DONE, TODO, SKIPPED, GATED, FAILED = "done", "todo", "skipped", "gated", "failed"

SYMBOL = {
    DONE: ("✓", "green"),
    TODO: ("○", "grey"),
    SKIPPED: ("⊘", "magenta"),
    GATED: ("▸", "grey"),
    FAILED: ("✗", "red"),
}

COLOURS = {
    "reset": "0", "bold": "1", "red": "31", "green": "32", "yellow": "33",
    "blue": "34", "magenta": "35", "cyan": "36", "grey": "90",
}

ENABLED = (sys.stdout.isatty()
           and os.environ.get("NO_COLOR") is None
           and os.environ.get("TERM") != "dumb")


def paint(text, colour):
    if not ENABLED:
        return str(text)
    return f"\033[{COLOURS[colour]}m{text}\033[0m"


def rule(width=72):
    print(paint("─" * width, "grey"))


def clear():
    if ENABLED:
        sys.stdout.write("\033[2J\033[H")


def render_prose(text):
    """Very small subset of markdown — enough to read nicely in a terminal."""
    text = re.sub(r"\*\*(.+?)\*\*", lambda m: paint(m.group(1), "bold"), text)
    text = re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)",
                  lambda m: paint(m.group(1), "bold"), text)
    text = re.sub(r"`([^`]+?)`", lambda m: paint(m.group(1), "cyan"), text)
    return text


# ------------------------------------------------------------------- parsing

# Values may be double quoted, single quoted or bare. Shell one-liners are full
# of quotes, so escaped quotes inside a quoted value have to survive — without
# this, check="test \"$(...)\" = 0" silently truncates at the first \" and the
# step reads as never done.
ATTR = re.compile(r'(\w+)=(?:"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\'|(\S+))')
FENCE = re.compile(r"^```(\w*)\s*(\{(.*)\})?\s*$")


def unescape(value):
    return re.sub(r'\\(["\'\\])', r"\1", value)


def parse_attrs(raw):
    out = {}
    for match in ATTR.finditer(raw or ""):
        double, single, bare = match.group(2), match.group(3), match.group(4)
        value = double if double is not None else (
            single if single is not None else (bare or ""))
        out[match.group(1)] = unescape(value)
    return out


def env_name(step_id):
    """Answers reach commands as environment variables: github-user -> GITHUB_USER."""
    return re.sub(r"[^A-Z0-9]", "_", step_id.upper())


def answers_env(state):
    env = dict(os.environ)
    # Commands run with the repo as their working directory, so relative paths
    # are the natural way to name things in it. $RUNBOOK_ROOT is for the cases
    # that genuinely need an absolute path anyway — the target of a symlink,
    # say, which has to keep resolving long after the command has finished.
    env["RUNBOOK_ROOT"] = ROOT
    for key, value in state.get("answers", {}).items():
        env[env_name(key)] = value
    return env


VAR_REF = re.compile(r"\$\{([A-Za-z_]\w*)\}|\$([A-Za-z_]\w*)")


def expand(text, env):
    """Substitute $VAR from the answers, not just the process environment.

    os.path.expandvars only sees os.environ, which never contains the answers —
    it would leave "$NEXT_RUNBOOK" sitting there literally.
    """
    def replace(match):
        name = match.group(1) or match.group(2)
        return env.get(name, match.group(0))
    return VAR_REF.sub(replace, text)


class Step:
    def __init__(self, id, title, phase, body, prose, kind, check, needs,
                 default=None, secret=False, capture=None):
        self.id = id
        self.title = title
        self.phase = phase
        self.body = body
        self.prose = prose
        self.kind = kind
        self.check = check
        self.needs = needs
        self.default = default
        self.secret = secret
        self.capture = capture

    def is_done(self, env=None):
        if not self.check:
            return False
        try:
            return subprocess.run(
                self.check, shell=True, timeout=120, env=env, cwd=ROOT,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            ).returncode == 0
        except Exception:
            return False

    def status(self, state, done_ids, env=None):
        # An answered question is done, and stays done across runs — that is
        # the point of asking. Secrets are not persisted, so they are asked
        # again each run.
        if self.kind == "ask":
            if self.secret:
                return DONE if self.id in state.get("session", {}) else TODO
            return DONE if self.id in state.get("answers", {}) else TODO

        if self.capture and self.capture in state.get("answers", {}):
            return DONE
        if self.is_done(env):
            return DONE
        record = state.get("steps", {}).get(self.id, {})
        if record.get("skipped"):
            return SKIPPED
        if any(need not in done_ids for need in self.needs):
            return GATED
        if record.get("done_at") and not self.check:
            # No probe available, so trust the journal for this one.
            return DONE
        if record.get("failed"):
            return FAILED
        return TODO


def parse(path):
    """Pull a title, phase list and steps out of a markdown document."""
    with open(path) as handle:
        lines = handle.read().splitlines()

    title = os.path.basename(path)
    phase = "Steps"
    heading = None
    prose = []
    steps = []
    i = 0

    while i < len(lines):
        line = lines[i]

        if line.startswith("# ") and not line.startswith("## "):
            title = line[2:].strip()
            prose = []
        elif line.startswith("### "):
            heading = line[4:].strip()
            prose = []
        elif line.startswith("## "):
            phase = line[3:].strip()
            heading = None
            prose = []
        elif FENCE.match(line):
            match = FENCE.match(line)
            lang, attrs = match.group(1), parse_attrs(match.group(3))
            body = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                body.append(lines[i])
                i += 1
            if "id" in attrs:
                kind = attrs.get("kind") or {
                    "manual": "manual", "ask": "ask",
                    "runbook": "runbook"}.get(lang, "auto")
                # A default may name an environment variable, so a launcher can
                # pre-fill an answer without rewriting the document. Unset
                # variables collapse to empty, which just means "ask me".
                default = attrs.get("default")
                if default:
                    default = os.path.expandvars(default).strip() or None
                steps.append(Step(
                    id=attrs["id"],
                    title=heading or attrs["id"],
                    phase=phase,
                    body="\n".join(body).strip(),
                    prose="\n".join(prose).strip(),
                    kind=kind,
                    check=attrs.get("check"),
                    needs=[n for n in attrs.get("needs", "").split(",") if n],
                    default=default,
                    secret=attrs.get("secret", "").lower() in ("true", "yes"),
                    capture=attrs.get("capture"),
                ))
            prose = []
        else:
            prose.append(line)
        i += 1

    return title, steps


# --------------------------------------------------------------------- state

def attach_terminal():
    """Point stdin at the terminal, whatever the runner was launched from.

    `curl … | bash` leaves the script's stdin on the pipe, and by the time the
    runner starts that pipe is drained — so every prompt reads EOF, which
    looks exactly like the operator pressing q. The runbook appears to abort
    on the first step it wants an answer for.

    dup2 rather than just reassigning sys.stdin, because the interactive steps
    are the ones that matter most here: `gh auth login` and the Homebrew
    installer inherit file descriptor 0, and they need the terminal too.

    Returns False when there is no terminal to attach — a cron job or a CI
    box — which is a thing to say plainly rather than to discover one silent
    quit at a time.
    """
    if sys.stdin.isatty():
        return True
    try:
        fd = os.open("/dev/tty", os.O_RDONLY)
    except OSError:
        return False
    try:
        os.dup2(fd, 0)
    finally:
        os.close(fd)
    sys.stdin = os.fdopen(0)
    return sys.stdin.isatty()


def runbook_root(path):
    """Where the document's commands should run: the repo holding it.

    A runbook is written from the point of view of its own checkout —
    `./setup-fish.sh`, `--file Brewfile` — so which directory the machine
    happened to clone it into must not leak into the document. Walk up from
    the file looking for a checkout, and settle for the file's own directory
    when there is not one, which is the case for a first-phase runbook fetched
    to a scratch directory rather than cloned.

    Deliberately not `git rev-parse`: this runs before the machine
    necessarily has a working git, and stat-ing a few parents is cheaper than
    a subprocess anyway.
    """
    directory = os.path.dirname(os.path.abspath(path))
    candidate = directory
    while True:
        if any(os.path.exists(os.path.join(candidate, marker))
               for marker in (".git", ".jj", ".hg")):
            return candidate
        parent = os.path.dirname(candidate)
        if parent == candidate:
            return directory
        candidate = parent


def state_path(path):
    slug = re.sub(r"[^a-z0-9]+", "-", os.path.basename(path).lower()).strip("-")
    return os.path.join(STATE_DIR, f"{slug}.json")


def load_state(path):
    try:
        with open(state_path(path)) as handle:
            state = json.load(handle)
    except (OSError, ValueError):
        state = {}
    if "steps" not in state and "answers" not in state:
        state = {"steps": state}  # migrate the original flat shape
    state.setdefault("steps", {})
    state.setdefault("answers", {})
    state["session"] = {}  # secrets, held in memory for this run only
    return state


def save_state(path, state):
    os.makedirs(STATE_DIR, exist_ok=True)
    target = state_path(path)
    tmp = target + ".tmp"
    on_disk = {k: v for k, v in state.items() if k != "session"}
    with open(tmp, "w") as handle:
        json.dump(on_disk, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp, target)


# --------------------------------------------------------------------- board

def evaluate(steps, state):
    statuses, done_ids = {}, set()
    # Answers are rebuilt as we go, so a question asked early is visible to the
    # checks of every step below it.
    for step in steps:
        status = step.status(state, done_ids, answers_env(state))
        statuses[step.id] = status
        if status == DONE:
            done_ids.add(step.id)
    return statuses


def draw(title, steps, state, statuses):
    total = len(steps)
    complete = sum(1 for s in statuses.values() if s in (DONE, SKIPPED))
    width = 40
    filled = int(width * complete / total) if total else 0

    print()
    print(f"  {paint(title, 'bold')}")
    print(f"  {paint('█' * filled, 'green')}{paint('░' * (width - filled), 'grey')}"
          f"  {complete}/{total}")
    print()

    for phase in dict.fromkeys(s.phase for s in steps):
        print(f"  {paint(phase.upper(), 'cyan')}")
        for step in [s for s in steps if s.phase == phase]:
            status = statuses[step.id]
            mark, colour = SYMBOL[status]
            name = step.title if status != DONE else paint(step.title, "grey")
            line = f"    {paint(mark, colour)} {name}"
            trailer = ""
            if status == GATED:
                trailer = "waiting on " + ", ".join(step.needs)
            elif status == SKIPPED:
                trailer = "declined"
            elif status == FAILED:
                trailer = "failed last run"
            elif step.kind == "ask" and status == DONE and not step.secret:
                trailer = f"{env_name(step.id)}={state['answers'][step.id]}"
                colour = "grey"
            elif status == TODO and step.kind == "ask":
                trailer = "question"
            elif status == TODO and step.kind == "manual":
                trailer = "manual"
            elif status == TODO and not step.check:
                trailer = "no check — run to mark done"
            if trailer:
                line += " " * max(1, 46 - len(step.title)) + paint(trailer, colour)
            print(line)
        print()


# ----------------------------------------------------------------- execution

def prompt(options):
    rendered = "   ".join(f"{paint('[' + k + ']', 'bold')} {label}"
                          for k, label in options)
    while True:
        print()
        print("  " + rendered)
        try:
            answer = input("  > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return "q"
        if answer == "":
            return options[0][0]
        for key, _ in options:
            if answer == key:
                return key


VAR = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")
SHELL_TOKEN = re.compile(
    r"""(?P<comment>\#.*$)
      | (?P<string>"[^"]*"|'[^']*')
      | (?P<var>\$\{?[A-Za-z_][A-Za-z0-9_]*\}?)
      | (?P<flag>(?<=\s)-{1,2}[A-Za-z][\w-]*)
      | (?P<op>\|\||&&|[|><]|;)
    """, re.VERBOSE)


def highlight(line):
    """Light shell colouring — enough to read, not a christmas tree."""
    def paint_match(match):
        for group, colour in (("comment", "grey"), ("string", "yellow"),
                              ("var", "magenta"), ("flag", "blue"),
                              ("op", "grey")):
            if match.group(group):
                return paint(match.group(group), colour)
        return match.group(0)
    return SHELL_TOKEN.sub(paint_match, line)


def boxed(lines, label, colour, highlighted=True):
    print(f"  {paint('┌─ ' + label + ' ', colour)}"
          f"{paint('─' * max(0, 60 - len(label)), 'grey')}")
    for line in lines:
        rendered = highlight(line) if highlighted else paint(line, "cyan")
        print(f"  {paint('│', colour)} {rendered}".rstrip())
    print(f"  {paint('└' + '─' * 63, 'grey')}")


def show(step, state=None):
    env = answers_env(state or {})
    rule()
    kind_label = {"manual": "by hand", "interactive": "interactive"}.get(
        step.kind, "command")
    print(f"  {paint(step.title, 'bold')}"
          f"  {paint(step.phase, 'grey')}"
          f"  {paint('· ' + kind_label, 'grey')}")

    if step.prose:
        print()
        for line in step.prose.splitlines():
            print(f"  {render_prose(line)}".rstrip())
    print()

    if step.kind == "manual":
        boxed(step.body.splitlines(), "do this yourself", "cyan",
              highlighted=False)
    else:
        boxed(step.body.splitlines(), "will run", "green")

    # Anything the step will interpolate, shown resolved so there are no
    # surprises about what actually executes.
    used = {}
    for name in VAR.findall(step.body + " " + (step.check or "")):
        if name in {env_name(k) for k in (state or {}).get("answers", {})}:
            used[name] = env.get(name, "")
    if used:
        pairs = "  ".join(f"{paint('$' + k, 'magenta')}={paint(v, 'yellow')}"
                          for k, v in sorted(used.items()))
        print(f"  {paint('using', 'grey')}     {pairs}")

    if step.check:
        print(f"  {paint('done when', 'grey')} {highlight(step.check)}")
    else:
        print(paint("  done when  (no check — it will be marked done by hand)",
                    "grey"))
    if step.needs:
        print(f"  {paint('after', 'grey')}     "
              f"{paint(', '.join(step.needs), 'grey')}")


def ask(step, path, state):
    """Put a question, remember the answer for every run after this one."""
    rule()
    print(f"  {paint(step.title, 'bold')}  {paint(step.phase, 'grey')}")
    if step.prose:
        print()
        for line in step.prose.splitlines():
            print(f"  {render_prose(line)}".rstrip())
    print()
    question = step.body or step.title
    suffix = f" [{step.default}]" if step.default else ""
    print(f"  {render_prose(question)}{paint(suffix, 'grey')}")
    print(paint(f"  → available to later steps as ${env_name(step.id)}", "grey"))
    print()
    try:
        if step.secret:
            import getpass
            answer = getpass.getpass("  > ")
        else:
            answer = input("  > ").strip()
    except (EOFError, KeyboardInterrupt):
        return False

    if not answer and step.default:
        answer = step.default
    if not answer:
        print(paint("  nothing entered — asking again next time", "yellow"))
        return True

    # People type ~ for paths, and the shell will not expand it once the value
    # arrives through an environment variable — `test -d $P/x` would look for a
    # directory literally named "~". Expand it here, where the intent is clear.
    if answer.startswith("~"):
        answer = os.path.expanduser(answer)

    if step.secret:
        state["session"][step.id] = answer
        print(paint("  ✓ held for this run only, not written to disk", "green"))
    else:
        state["answers"][step.id] = answer
        save_state(path, state)
        print(paint(f"  ✓ saved — {env_name(step.id)}={answer}", "green"))
    return True


def handover(step, path, state):
    """Hand off to another runbook — the last step of a bootstrap phase.

    The child keeps its own state file, because it is a separate process with a
    separate life: quitting the child does not un-finish the parent, and
    re-running either one picks up where it was.
    """
    env = answers_env(state)
    target = os.path.expanduser(expand(step.body.strip(), env))
    show(step, state)
    print()
    print(f"  {paint('hands over to', 'grey')} {paint(target, 'cyan')}")

    if not os.path.exists(target):
        print(paint(f"  not found: {target}", "red"))
        print(paint("  finish the step that fetches it, then come back", "grey"))
        # Passing it over matters: a step that stays pending without being
        # marked would be offered again immediately, forever.
        state["session"].setdefault("passed", []).append(step.id)
        return True

    choice = prompt([("enter", "continue there"), ("s", "not now"),
                     ("q", "quit")])
    if choice == "q":
        return False
    if choice == "s":
        state["session"].setdefault("passed", []).append(step.id)
        return True

    state["steps"].setdefault(step.id, {})["done_at"] = True
    save_state(path, state)
    print(paint(f"\n  → runbook {target}\n", "grey"))
    subprocess.run([sys.executable, os.path.abspath(__file__), target], env=env)
    return True


def handle(step, path, state):
    if step.kind == "ask":
        return ask(step, path, state)
    if step.kind == "runbook":
        return handover(step, path, state)

    show(step, state)
    verb = "done" if step.kind == "manual" else "run"
    choice = prompt([("enter", verb), ("s", "not now"), ("n", "never"),
                     ("q", "quit")])
    record = state["steps"].setdefault(step.id, {})

    if choice == "q":
        return False
    if choice == "s":
        # Passed over for this run only — it will come round again next time.
        state["session"].setdefault("passed", []).append(step.id)
        print(paint("  left for next time", "yellow"))
        return True
    if choice == "n":
        record["skipped"] = True
        save_state(path, state)
        print(paint("  declined — it will not be offered again "
                    "(--reset to undo)", "magenta"))
        return True

    env = answers_env(state)

    if step.kind == "manual":
        if step.check and not step.is_done(env):
            print(paint("  still not detected — leaving it open", "yellow"))
        else:
            record["done_at"] = True
            print(paint("  ✓ recorded", "green"))
        save_state(path, state)
        return True

    print()
    if step.capture:
        # The step computes something a later step needs — its last line of
        # output becomes an answer, so paths and ids can be discovered at run
        # time rather than hard-coded into the document.
        result = subprocess.run(["/bin/bash", "-c", step.body], env=env,
                                cwd=ROOT, stdout=subprocess.PIPE, text=True)
        code = result.returncode
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
        value = [ln for ln in result.stdout.splitlines() if ln.strip()]
        if code == 0 and value:
            state["answers"][step.capture] = value[-1].strip()
            save_state(path, state)
            print(paint(f"  ✓ {env_name(step.capture)}="
                        f"{state['answers'][step.capture]}", "green"))
            return True
    else:
        code = subprocess.run(["/bin/bash", "-c", step.body], env=env,
                              cwd=ROOT).returncode

    if code == 0 or step.is_done(env):
        record.pop("failed", None)
        record["done_at"] = True
        print(paint("  ✓ done", "green"))
    else:
        record["failed"] = True
        print(paint(f"  ✗ exited {code}", "red"))
    save_state(path, state)
    return True


# ---------------------------------------------------------------------- main

def main():
    args = [a for a in sys.argv[1:]]
    files = [a for a in args if not a.startswith("--")]
    if not files:
        print(__doc__.strip().split("\n\n")[1])
        return 2

    path = files[0]
    if not os.path.exists(path):
        print(f"no such runbook: {path}")
        return 1

    # Steps run in the repo holding the document, not in whatever directory
    # the runner was invoked from.
    global ROOT
    ROOT = runbook_root(path)

    if "--reset" in args:
        save_state(path, {"steps": {}, "answers": {}})
        print("state cleared, answers forgotten")
        return 0

    title, steps = parse(path)

    if "--ask" in args:
        state = load_state(path)
        wanted = args[args.index("--ask") + 1:]
        if not wanted:
            for key, value in sorted(state["answers"].items()):
                print(f"  {env_name(key)}={value}")
            return 0
        if not attach_terminal():
            print("--ask needs a terminal to read the new answer from")
            return 1
        for step in steps:
            if step.kind == "ask" and step.id in wanted:
                state["answers"].pop(step.id, None)
                ask(step, path, state)
        return 0
    if not steps:
        print(f"{path} has no fenced blocks with an id= attribute")
        return 1

    state = load_state(path)
    last_offered, repeats = None, 0

    if "--list" in args:
        draw(title, steps, state, evaluate(steps, state))
        return 0

    if "--check" in args:
        # Machine-readable, for scripts and CI: one id per unfinished step,
        # nothing at all when everything passes, exit 1 if any remain. Points a
        # build at a runbook so documentation cannot rot unnoticed.
        statuses = evaluate(steps, state)
        outstanding = [s for s in steps if statuses[s.id] not in (DONE, SKIPPED)]
        for step in outstanding:
            print(f"{step.id}\t{statuses[step.id]}\t{step.title}")
        return 1 if outstanding else 0

    # --list and --check are the modes that make sense without a person; from
    # here every step is offered to one.
    if not attach_terminal():
        print("Nothing to read answers from — stdin is not a terminal and")
        print("/dev/tty could not be opened. --list and --check work without")
        print("one; stepping through does not.")
        return 1

    while True:
        statuses = evaluate(steps, state)
        clear()
        draw(title, steps, state, statuses)
        passed = state["session"].get("passed", [])
        pending = [s for s in steps
                   if statuses[s.id] in (TODO, FAILED) and s.id not in passed]
        if not pending:
            rule()
            if passed:
                print(paint(f"  {len(passed)} step(s) left for next time. "
                            "Everything else is done. ✨", "yellow"))
            else:
                print(paint("  Nothing left to do. ✨", "green"))
            print()
            return 0
        step = pending[0]
        # Insurance: any handler that returns without finishing, declining or
        # passing its step would see it offered again immediately and spin
        # forever. Rather than trust every branch of every handler, notice.
        repeats = repeats + 1 if step.id == last_offered else 0
        last_offered = step.id
        if repeats >= 3:
            print(paint(f"  {step.title} is not settling — passing it over. "
                        "This is a bug worth reporting.", "red"))
            state["session"].setdefault("passed", []).append(step.id)
            continue

        if not handle(step, path, state):
            print()
            print(paint(f"  Stopped. Resume with ./runbook.py {path}", "grey"))
            print()
            return 0
        # A question produces nothing to read, so pausing after it just makes
        # you press enter twice. Commands do, so hold there.
        if step.kind != "ask":
            prompt([("enter", "continue")])


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print(paint("\n\n  Stopped — re-run to resume.\n", "grey"))
        sys.exit(0)

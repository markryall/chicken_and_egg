# chicken_and_egg

A new machine can't run your setup, because your setup lives in a repo the
machine can't clone yet, because it has no git, no credentials and no you.

This is the smallest thing that breaks that cycle, plus the runner it installs
along the way.

```bash
curl -fsSL https://raw.githubusercontent.com/markryall/chicken_and_egg/main/install.sh | bash
```

Name the repo holding your own setup and it will fetch that too once the
machine can authenticate:

```bash
curl -fsSL .../install.sh | bash -s -- markryall/dotfiles-private
```

Nothing before the GitHub sign-in needs credentials — that split is the whole
design, and it's why this half can be public and fetched by a stranger.

## What it actually does

```
curl | bash
  └─ Command Line Tools, then install the runner, then hand it a runbook
       1  Command Line Tools          check: xcode-select -p
       2  ~/.local/bin on PATH        check: PATH, or a line in ~/.zshrc
       3  Homebrew                    check: command -v brew
       4  GitHub CLI                  check: command -v gh
       5  gh auth login               check: gh auth status      ← the gate
       6  Which runbook?              asked once, remembered
       7  Clone it                    check: the directory exists
       8  Find the runbook inside     runbook.md, runbooks/laptop.md, ...
       9  Hand over ─────────────────────────────────┐
                                                     ▼
                                        your own runbook takes it from here
```

## The runner

`runbook.py` runs a markdown document as an interactive, resumable process.
Prose explains each step, a fenced block says what to run, and an annotation
says how to tell whether it's already been done.

````markdown
### Install the Ruby toolchain

We use mise rather than asdf, so a Makefile expecting asdf shims will look
broken until you know that.

```bash {id=ruby check="mise which ruby"}
mise install
```
````

Zero dependencies. It runs on the Python that ships with macOS, which is what
lets it go *before* Homebrew rather than after.

### Blocks

| Language | Does |
|---|---|
| `bash` | Runs the command |
| `manual` | Prints instructions and waits for a human |
| `ask` | Puts a question and remembers the answer |
| `runbook` | Hands over to another runbook |

### Attributes

| | |
|---|---|
| `id=slug` | Required. Identifies the step in the state file |
| `check="cmd"` | Exit 0 means already done |
| `needs=a,b` | Hold the step back until those are done |
| `kind=interactive` | Hand the terminal over rather than capturing output |
| `capture=name` | The step's last line of output becomes an answer |
| `default="x"` | Questions only. `$VAR` here is read from the environment |
| `secret=true` | Questions only. No echo, and deliberately never persisted |

Answers reach later steps as environment variables named after the id, in both
the command and its `check` — `id=github-user` becomes `$GITHUB_USER`. Ask
once, personalise forever.

### Where steps run

In the repo holding the runbook — the nearest parent with a `.git`, `.jj` or
`.hg`, or the document's own directory when it is not a checkout. A runbook
can therefore say `./setup-fish.sh` and `brew bundle check --file Brewfile`
and be right no matter where the machine cloned it, which is the difference
between a document that describes your laptop and one that describes your
laptop's file paths. `$RUNBOOK_ROOT` is that directory, for the handful of
commands that need an absolute path regardless — the target of a symlink, say.

## Why a check, and not a log of what ran

Every comparable tool records whether *it* performed a step. That's a journal,
and a journal is empty on a machine somebody else set up, or one configured by
hand last Tuesday, or one where you did half the list before getting
distracted.

A check asks the machine instead. Delete the state file entirely and the board
re-derives itself; do half the steps by hand and it notices. For onboarding
that matters more than anything else here, because "already done" is the
common case rather than the exception.

The state file (`~/.local/state/runbook/<name>.json`) therefore holds only what
a probe can't infer: your answers, and anything you declined.

## Using it

```bash
runbook <file.md>             # step through whatever isn't done
runbook <file.md> --list      # print the board, change nothing
runbook <file.md> --ask       # show remembered answers
runbook <file.md> --ask <id>  # change one
runbook <file.md> --reset     # forget answers and declines
```

At each step: **enter** runs it, **s** leaves it for next time, **n** declines
it for good, **q** quits. Already-completed steps are never offered.

`runbooks/demo.md` is a harmless playground that writes only to
`/tmp/runbook-demo`.

## Piping curl into bash

You should be suspicious of that, so: `install.sh` is deliberately short and
boring, and reads top to bottom in a minute. If you'd rather look first:

```bash
curl -fsSL .../install.sh -o /tmp/cae.sh && less /tmp/cae.sh && bash /tmp/cae.sh
```

It writes exactly two things — `~/.local/bin/runbook`, and a scratch copy of
the first-phase runbook under `$TMPDIR`. Everything after that is a step you
approve one at a time.

One wrinkle worth knowing about, because it bites every `curl | bash`
installer that then wants to ask you something: piped in, the script *is*
stdin, and that pipe is drained by the time the runner starts. So the runner
reopens `/dev/tty` and hands it to its own prompts and to the interactive
steps it spawns. Without that, every question reads EOF — which is
indistinguishable from you pressing q, so the runbook appears to abort on the
first step it wants an answer for.

## Status

Young, and honest about it. Written in a couple of evenings, tested against two
real documents on macOS, and since run end to end on a fresh Mac — which found
two things nothing else would have: prompts reading EOF under `curl | bash`,
and a runbook that had quietly hard-coded where its own repo was cloned. It has
still never been run by someone who isn't its author, which is the only test
that really counts.

macOS only for now. Nothing in the runner is Mac-specific; `install.sh` and the
first-phase runbook very much are.

## Licence

MIT.

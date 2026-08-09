# Runbook demo

A safe playground for `runbook.py`. Everything here writes to `/tmp/runbook-demo/`
and nothing touches your real setup, so poke at it freely.

Try this: run it, answer the questions, do a couple of steps, decline one, quit
part way through — then run it again and watch it pick up exactly where you
left off without redoing anything.

```bash
./runbook.py runbooks/demo.md
./runbook.py runbooks/demo.md --list    # look without touching
./runbook.py runbooks/demo.md --ask     # show the answers it remembered
./runbook.py runbooks/demo.md --reset   # forget answers and declines
```

## Resetting it

There are two halves to undo, and the split between them is the whole idea.

**What the steps did** lives in `/tmp/runbook-demo`. Delete it and every check
fails again, so the board empties out on its own:

```
rm -rf /tmp/runbook-demo
```

**What you told it** — your answers, and anything you declined with `n` — lives
in `~/.local/state/runbook/demo-md.json`, because no probe could ever recover
your name from the filesystem:

```
./runbook.py runbooks/demo.md --reset
```

Do only the first and the steps come back but it still knows who you are. Do
only the second and it forgets your name while the work stays done. Both, for a
completely clean slate.

## Questions

### What should I call you?

Questions are asked once and remembered. The answer becomes an environment
variable for every step below — this one arrives as `$YOUR_NAME` — so a shared
runbook personalises itself per person on first run.

```ask {id=your-name default="gorgeous"}
Your name
```

### Which editor do you use?

Answers can carry a default, offered when you just press enter. Handy for
anything with an obvious house answer that the odd person needs to override.

```ask {id=editor default="emacs"}
Preferred editor
```

## Doing things

### Create the demo directory

An ordinary step. The `check` is what makes this whole thing resumable: it asks
the filesystem whether the directory exists rather than remembering whether we
made it. Delete the state file and this stays ticked; make the directory by
hand and it ticks without ever running.

```bash {id=mkdir check="test -d /tmp/runbook-demo"}
mkdir -p /tmp/runbook-demo && echo "created /tmp/runbook-demo"
```

### Write a greeting using your answer

Both the command *and* its check can read the answers, which is what makes
questions worth persisting — this step is checked against a filename that
depends on what you typed.

```bash {id=greeting needs=mkdir check="test -f /tmp/runbook-demo/hello-$YOUR_NAME.txt"}
echo "hello $YOUR_NAME, writing this from $EDITOR" > "/tmp/runbook-demo/hello-$YOUR_NAME.txt"
cat "/tmp/runbook-demo/hello-$YOUR_NAME.txt"
```

### A step you might not want

Nothing here is compulsory. **s** leaves a step for next time, **n** declines it
for good — try `n` on this one, then re-run and watch it sit there as declined
rather than nagging. `--reset` brings it back.

```bash {id=optional needs=mkdir check="test -f /tmp/runbook-demo/optional"}
touch /tmp/runbook-demo/optional && echo "the optional thing happened"
```

### Something only you can do

Some steps can't be scripted — granting macOS permissions, clicking something
in a web console, asking someone for access. A `manual` block explains the job
and waits; the check then confirms it actually happened, so you can't tick past
it by accident. Try pressing enter without doing it.

```manual {id=by-hand needs=mkdir check="test -f /tmp/runbook-demo/by-hand"}
Run this yourself in another terminal:

    touch /tmp/runbook-demo/by-hand
```

## Finishing

### A step that waits for the rest

`needs` holds a step back until its dependencies are done, so the board shows
what's genuinely available now rather than a flat list of forty things.

```bash {id=summary needs=greeting,by-hand check="test -f /tmp/runbook-demo/done"}
ls -1 /tmp/runbook-demo && touch /tmp/runbook-demo/done && echo "all done, $YOUR_NAME"
```

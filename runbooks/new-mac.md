# A brand new Mac

Getting a fresh machine to the point where it can set itself up.

Everything here is deliberately generic and needs no credentials — that is why
it can live in a public repo and be fetched by a stranger. The moment this
finishes, your own runbook takes over and does the parts that are actually
about you.

## Foundations

### Command Line Tools

Already done by the installer that brought you here — `git` and `python3` both
come from this, and nothing else can happen without them.

```bash {id=clt check="/usr/bin/xcode-select -p"}
/usr/bin/xcode-select --install
```

### Put ~/.local/bin on your PATH

The runner was installed to `~/.local/bin`. Adding that directory to your PATH
means `runbook` works as a plain command from now on, in this shell and every
future one.

This appends to `~/.zshrc` because zsh is the macOS default. If you end up on
fish or bash later, your own runbook is the right place to sort that out.

```bash {id=path check="case \":$PATH:\" in *\":$HOME/.local/bin:\"*) exit 0;; esac; grep -q '.local/bin' ~/.zshrc 2>/dev/null"}
mkdir -p ~/.local/bin
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
echo "added to ~/.zshrc — new shells will pick it up"
```

### Homebrew

Nearly everything else is installed with it. The installer prints a couple of
post-install commands to add brew to your PATH — **run them**, or the next step
will not find it.

```bash {id=brew kind=interactive check="command -v brew || test -x /opt/homebrew/bin/brew"}
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

## Getting you access

### The GitHub CLI

```bash {id=gh needs=brew check="command -v gh"}
eval "$(/opt/homebrew/bin/brew shellenv)"
brew install gh
```

### Sign in to GitHub

This is the gate. Everything before it is public and generic; everything after
it is yours, and none of it can be fetched until this succeeds.

Choose HTTPS when asked unless you already have a strong opinion — you can add
SSH keys later, and your own runbook probably does.

```bash {id=gh-auth kind=interactive needs=gh check="gh auth status"}
gh auth login
```

## Your runbook

### Which runbook should take over?

An `owner/repo` on GitHub — `markryall/dotfiles-private`, `Fresho-Org/fresho`,
whatever holds your setup. It can be private now that you are signed in.

Leave it blank if you do not have one yet and the demo runbook will be offered
instead, so you can see how this works before writing your own.

```ask {id=target default="$RUNBOOK_TARGET"}
Which repo holds your runbook? (owner/repo)
```

### Where should it be cloned?

```ask {id=code-dir default="~/code"}
Directory to clone into
```

### Clone it

```bash {id=clone needs=gh-auth check="test -n \"$TARGET\" && test -d \"$CODE_DIR/$TARGET\""}
mkdir -p "$CODE_DIR/$(dirname "$TARGET")"
gh repo clone "$TARGET" "$CODE_DIR/$TARGET"
```

### Find the runbook inside it

Convention rather than configuration: `runbook.md` at the root, else
`runbooks/laptop.md`, else whatever single runbook is in `runbooks/`. If none
of those exist, this tells you what it looked for.

The last line this prints becomes `$NEXT_RUNBOOK`, which the handover below
uses — so the path is discovered rather than written down twice.

```bash {id=locate needs=clone capture=next-runbook}
repo="$CODE_DIR/$TARGET"
for candidate in runbook.md runbooks/laptop.md runbooks/setup.md; do
  [ -f "$repo/$candidate" ] && echo "$repo/$candidate" && exit 0
done
only=$(ls "$repo"/runbooks/*.md 2>/dev/null)
if [ "$(echo "$only" | grep -c .)" = "1" ]; then
  echo "$only"
  exit 0
fi
echo "No runbook found in $repo" >&2
echo "Looked for runbook.md, runbooks/laptop.md, runbooks/setup.md" >&2
exit 1
```

### Over to you

That is the end of the generic part. From here your own runbook knows what to
do, and this one is finished for good.

```runbook {id=handoff needs=locate}
$NEXT_RUNBOOK
```

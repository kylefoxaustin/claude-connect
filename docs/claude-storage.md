# Claude Code on-disk storage — empirical notes

> Verified by inspection on Claude Code CLI ≥ 1.x on Linux. Format is undocumented and subject to change; this file is the source of truth for what Conductor expects.

## Root: `~/.claude/`

```
~/.claude/
├── projects/
│   └── <encoded-cwd>/
│       └── <session-id>.jsonl
├── todos/
├── settings.json
└── ...
```

## Project directory hashing

Claude encodes the working-directory path into a single directory name under `~/.claude/projects/`. Empirically the current encoding replaces **every non-alphanumeric character** with `-` (so `/`, `_`, `.`, spaces all become `-`, and the leading `/` becomes the leading dash):

```
cwd                              encoded
/home/user/code/api         →    -home-user-code-api
/home/user/elm7_engine      →    -home-user-elm7-engine    (underscore → dash)
/home/user/my.app           →    -home-user-my-app         (dot → dash)
```

> ⚠️ **Encoding changed across Claude versions.** Older Claude only replaced `/`, leaving `_`/`.` intact — so stale dirs like `…elm7_engine` can coexist with current `…elm7-engine` dirs. Conductor follows the current rule; a session whose dir was created by an old Claude (underscore preserved) won't be matched until that session writes under the new encoding.

Implementation in `conductor/scanner.py::encode_cwd()`:

```python
def encode_cwd(path: str) -> str:
    p = os.path.realpath(path)
    return re.sub(r"[^A-Za-z0-9]", "-", p)
```

If the encoding ever changes, fall back to:
```
candidates = list(Path("~/.claude/projects").expanduser().iterdir())
match = max(candidates, key=lambda d: d.stat().st_mtime)  # most recent
```

## Session JSONL

Each session writes one JSONL file: `~/.claude/projects/<encoded>/<session-id>.jsonl`.

One JSON object per line. Common record shapes Conductor relies on:

- `type == "summary"` — has `summary` field; written when `/rename` is invoked. **This is how we resolve the tile title.**
- `type == "user"` or `"assistant"` — message records with `message.content`. Used for the activity preview.
- `type == "system"` — internal events (rarely user-visible).

Pseudo-schema:
```jsonc
{ "type": "summary", "summary": "api-server", "leafUuid": "..." }
{ "type": "user",    "message": { "role": "user",      "content": [{"type": "text", "text": "..."}] }, "timestamp": "..." }
{ "type": "assistant","message":{ "role": "assistant", "content": [...] }, "timestamp": "..." }
```

### Title resolution algorithm

1. Tail the file in reverse (read last ~64 KiB, split on newlines).
2. Walk lines newest → oldest; first record with `type == "summary"` wins.
3. Use the `summary` field as the tile title.
4. If no summary record found, fall back to the project directory basename.

### Activity preview algorithm

1. On scan + on inotify-modify, read the last record.
2. Extract `message.content[*].text` (skipping non-text content blocks like tool_use).
3. Concatenate, take the last 200 characters.
4. Push over WebSocket.

## Activity classification

Conductor never reads the file content for status — it uses the `*.jsonl` mtime alone:

| age of mtime | status     | color      |
|-------------:|------------|------------|
| < 3s         | active     | green pulse |
| 3–30s        | warm       | yellow     |
| 30s–5m       | idle       | gray       |
| > 5m         | dormant    | dim gray   |

`waiting` is inferred separately: process alive AND no jsonl write in 30s AND CPU% < 1% over a 1s sample.

`ended` means the process has exited; the tile fades for `ui.end_fadeout_seconds` then is removed.

## Discovery edge cases

- **Filtering**: many processes have "claude" in their cmdline (grep, ripgrep, editors with the file open). Filter by `psutil.Process.exe()` resolving to the Claude Code CLI binary specifically — typically a Node script under `~/.nvm/...` or `/usr/local/lib/node_modules/@anthropic-ai/claude-code/cli.js`. Conductor uses a lenient match: `cmdline[0]` ends with `node` AND any cmdline arg path contains `@anthropic-ai/claude-code`.
- **Multiple Claudes per dir**: Conductor assumes one Claude per project dir. If two are detected, we take the most recent jsonl and surface a warning in the tile.
- **`/proc/<pid>/cwd`** requires either same-uid access or root. Conductor expects to run as the same user as the Claude processes.

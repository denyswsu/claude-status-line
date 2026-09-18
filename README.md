# claude-status-line

A four-line status line for [Claude Code](https://code.claude.com) written in plain Python.
No `jq`, no network calls, no extra dependencies.

```
◆ Fable 5.1 │ 📁 prounitas-backend (⎇ feature-branch*) │ $4.80 │ ⏱ 31m 58s │ ▸ Add statusline
context ●○○○○○○○○○  11% 111k/1M
current ○○○○○○○○○○   2% ⟳ 8:10am ▲0%
weekly  ●○○○○○○○○○  10% ⟳ sep 21, 5:00am ▲46%
```

## What it shows

**Line 1**

| Segment | Meaning |
|---|---|
| `◆ Fable 5.1` | Model display name, bold pink |
| `📁 dir (⎇ branch*)` | Current folder and git branch. `*` appears when the working tree has uncommitted changes |
| `$4.80` | Estimated session cost at API list price. Informational only on a subscription |
| `⏱ 31m 58s` | Wall-clock session duration |
| `▸ name` | Session name from `/rename` or the AI-generated title. Hidden when absent |

**Lines 2 to 4**: three aligned progress bars, ten circles each, filled to the nearest 10%.

| Row | Meaning |
|---|---|
| `context` | Context window used, plus tokens in context over the window size (`111k/1M`) |
| `current` | 5-hour rate limit used, `⟳` local reset time, and a pace indicator |
| `weekly` | 7-day rate limit used, `⟳` reset date and time, and a pace indicator |

Colors follow one scale everywhere: green below 50%, orange to 69%, yellow to 89%, red from 90%.

**Pace** compares your usage to a straight line from window start to reset.
`▲30%` means you have 30 points of headroom versus linear burn. `▼5%` means you are burning faster than linear.

When Claude Code does not send rate limit data, the row shows a dim placeholder so the layout never shifts.

## Install

```bash
mkdir -p ~/.claude
curl -sL https://raw.githubusercontent.com/denyswsu/claude-status-line/main/statusline.py -o ~/.claude/statusline.py
chmod +x ~/.claude/statusline.py
```

Then add to `~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "python3 ~/.claude/statusline.py",
    "padding": 0
  }
}
```

Optional: add `"refreshInterval": 30` inside `statusLine` so reset times and pace stay current while the session is idle.

Requires Python 3.6+ and a terminal with 256-color or true-color support.

## Debugging

Set `CLAUDE_STATUSLINE_DEBUG=1` in the environment Claude Code runs in and the script writes the last JSON it received to `~/.claude/statusline-last-input.json`.

Test locally with sample input:

```bash
echo '{"model":{"display_name":"Opus"},"cwd":"'$PWD'","cost":{"total_cost_usd":1.2,"total_duration_ms":754000},"context_window":{"used_percentage":42,"total_input_tokens":84000,"context_window_size":200000},"rate_limits":{"five_hour":{"used_percentage":30,"resets_at":'$(( $(date +%s) + 7200 ))'},"seven_day":{"used_percentage":74,"resets_at":'$(( $(date +%s) + 300000 ))'}}}' | python3 ~/.claude/statusline.py
```

## Credits

Started from [razamit's gist](https://gist.github.com/razamit/34670a1afa015c9224787ab133970e76).
The circle progress bars and the `current` / `weekly` layout are borrowed from [nilbuild/claude-statusline](https://github.com/nilbuild/claude-statusline) (MIT).

## License

MIT

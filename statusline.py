#!/usr/bin/env python3
"""Claude Code status line: model, folder/branch, cost, timer, and circle
progress bars for context, 5-hour and 7-day rate limits.

https://github.com/denyswsu/claude-status-line
"""
import json, sys, subprocess, os, time
from datetime import datetime

# Force UTF-8 output on Windows
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

raw = sys.stdin.read()
if os.environ.get('CLAUDE_STATUSLINE_DEBUG'):
    # Dump the last input Claude Code sent, handy when a segment looks wrong.
    try:
        with open(os.path.expanduser('~/.claude/statusline-last-input.json'), 'w') as _f:
            _f.write(raw)
    except Exception:
        pass
data = json.loads(raw)

model = data.get('model', {}).get('display_name') or data.get('model', {}).get('id', 'Unknown')
cwd = data.get('workspace', {}).get('current_dir') or data.get('cwd') or os.getcwd()
dirname = os.path.basename(cwd)
cost = data.get('cost', {}).get('total_cost_usd', 0) or 0
pct = int(data.get('context_window', {}).get('used_percentage', 0) or 0)
duration_ms = data.get('cost', {}).get('total_duration_ms', 0) or 0
cw = data.get('context_window', {}) or {}
ctx_tokens = (cw.get('total_input_tokens') or 0) + (cw.get('total_output_tokens') or 0)
ctx_size = cw.get('context_window_size') or 200000
session_name = data.get('session_name') or ''

CYAN    = '\033[36m'
BCYAN   = '\033[96m'
PINK    = '\033[38;5;213m'
BLUE    = '\033[38;5;75m'
AMBER   = '\033[38;2;220;168;19m'   # #dca813
GREEN   = '\033[32m'
YELLOW  = '\033[33m'
ORANGE  = '\033[38;5;214m'
RED     = '\033[31m'
WHITE   = '\033[37m'
DIM     = '\033[2m'
BOLD    = '\033[1m'
RESET   = '\033[0m'
SEP     = f' {DIM}│{RESET} '


def color_for_pct(p):
    if p >= 90:
        return RED
    if p >= 70:
        return YELLOW
    if p >= 50:
        return ORANGE
    return GREEN


mins = duration_ms // 60000
secs = (duration_ms % 60000) // 1000

# ── Git branch + dirty marker ────────────────────────────
branch = ''
try:
    subprocess.check_output(['git', '-C', cwd, 'rev-parse', '--git-dir'], stderr=subprocess.DEVNULL)
    b = subprocess.check_output(
        ['git', '-C', cwd, 'branch', '--show-current'], text=True, stderr=subprocess.DEVNULL
    ).strip()
    if b:
        dirty = ''
        try:
            st = subprocess.check_output(
                ['git', '-C', cwd, '--no-optional-locks', 'status', '--porcelain', '--untracked-files=no'],
                text=True, stderr=subprocess.DEVNULL
            )
            if st.strip():
                dirty = f'{YELLOW}*{RESET}'
        except Exception:
            pass
        branch = f' {DIM}({RESET}{BLUE}⎇ {b}{RESET}{dirty}{DIM}){RESET}'
except Exception:
    pass


# ── Rate limits as circle bars ───────────────────────────
def circle_bar(used_pct, width=10):
    used_pct = max(0, min(100, used_pct))
    n = (used_pct * width + 50) // 100  # round half up to nearest circle
    return f'{color_for_pct(used_pct)}{"●" * n}{DIM}{"○" * (width - n)}{RESET}'


def fmt_reset(resets_at, weekly):
    if not resets_at:
        return ''
    dt = datetime.fromtimestamp(resets_at)
    if weekly:
        s = dt.strftime('%b %-d, %-I:%M%p')
    else:
        s = dt.strftime('%-I:%M%p')
    return s.lower()


def pace_str(used_pct, resets_at, window_mins):
    """▲ = burning slower than linear (headroom), ▼ = burning faster."""
    now = int(time.time())
    if not resets_at or resets_at <= now:
        return ''
    remaining_mins = max(0, (resets_at - now) // 60)
    if remaining_mins > window_mins:
        return ''
    pace = (window_mins - remaining_mins) * 100 // window_mins - used_pct
    if pace >= 0:
        return f'{GREEN}▲{pace}%{RESET}'
    return f'{RED}▼{abs(pace)}%{RESET}'


def fmt_tokens(n):
    n = int(n)
    if n >= 1_000_000:
        v = n / 1_000_000
        return f'{v:.1f}M'.replace('.0M', 'M')
    if n >= 1_000:
        return f'{n // 1_000}k'
    return str(n)


def row(label, used_pct):
    used_pct = int(used_pct)
    return [
        f'{WHITE}{label:<7}{RESET}',
        circle_bar(used_pct),
        f'{color_for_pct(used_pct)}{used_pct:>3d}%{RESET}',
    ]


def limit_line(label, used_pct, resets_at, window_mins, weekly):
    parts = row(label, used_pct)
    reset_s = fmt_reset(resets_at, weekly)
    if reset_s:
        parts.append(f'{DIM}⟳{RESET} {WHITE}{reset_s}{RESET}')
    p = pace_str(used_pct, resets_at, window_mins)
    if p:
        parts.append(p)
    return ' '.join(parts)


def placeholder_line(label):
    return f'{WHITE}{label:<7}{RESET} {DIM}{"○" * 10}   –%  no data{RESET}'


rl = data.get('rate_limits') or {}
rl_lines = []

five_hour = rl.get('five_hour') or {}
if five_hour.get('used_percentage') is not None:
    rl_lines.append(limit_line('current', five_hour['used_percentage'],
                               five_hour.get('resets_at') or 0, 300, weekly=False))
else:
    rl_lines.append(placeholder_line('current'))

seven_day = rl.get('seven_day') or {}
if seven_day.get('used_percentage') is not None:
    rl_lines.append(limit_line('weekly', seven_day['used_percentage'],
                               seven_day.get('resets_at') or 0, 10080, weekly=True))
else:
    rl_lines.append(placeholder_line('weekly'))

# ── Output ───────────────────────────────────────────────
dur = f'{BCYAN}⏱ {mins}m {secs:02d}s{RESET}'
line1 = f"{BOLD}{PINK}◆ {model}{RESET}{SEP}{AMBER}📁 {dirname}{RESET}{branch}{SEP}{GREEN}${cost:.2f}{RESET}{SEP}{dur}"
if session_name:
    line1 += f"{SEP}{DIM}▸ {session_name}{RESET}"
print(line1)

ctx_parts = row('context', pct)
ctx_parts.append(f'{DIM}{fmt_tokens(ctx_tokens)}/{fmt_tokens(ctx_size)}{RESET}')
print(' '.join(ctx_parts))
for line in rl_lines:
    print(line)

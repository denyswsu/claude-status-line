#!/usr/bin/env python3
"""Claude Code status line: model, folder/branch, cost, timer, and circle
progress bars for context, 5-hour and 7-day rate limits, plus one bar per
model-scoped limit (e.g. Fable) read from Claude Code's cached usage snapshot.

https://github.com/denyswsu/claude-status-line
"""
import json, sys, subprocess, os, time, re, calendar
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


def row(label, used_pct, label_color=WHITE):
    used_pct = int(used_pct)
    return [
        f'{label_color}{label:<7}{RESET}',
        circle_bar(used_pct),
        f'{color_for_pct(used_pct)}{used_pct:>3d}%{RESET}',
    ]


def limit_line(label, used_pct, resets_at, window_mins, weekly, label_color=WHITE):
    parts = row(label, used_pct, label_color)
    reset_s = fmt_reset(resets_at, weekly)
    if reset_s:
        parts.append(f'{DIM}⟳{RESET} {WHITE}{reset_s}{RESET}')
    p = pace_str(used_pct, resets_at, window_mins)
    if p:
        parts.append(p)
    return ' '.join(parts)


def placeholder_line(label):
    return f'{WHITE}{label:<7}{RESET} {DIM}{"○" * 10}   –%  no data{RESET}'


# ── Model-scoped limits (Fable today, whatever comes next) ──
# Claude Code only puts the plain 5-hour and 7-day windows on stdin. The
# per-model weekly buckets are in the usage snapshot it caches in
# ~/.claude.json (cachedUsageUtilization.utilization.limits[]), refreshed at
# most once a minute while a session is active and valid for an hour.
STALE_AFTER_SECS = 15 * 60


def parse_iso(s):
    """ISO-8601 timestamp → epoch seconds. Hand-rolled so Python 3.6 works."""
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(Z|[+-]\d{2}:?\d{2})?$', s or '')
    if not m:
        return 0
    ts = calendar.timegm(tuple(int(x) for x in m.groups()[:6]))
    tz = m.group(7)
    if tz and tz != 'Z':
        off = tz[1:].replace(':', '')
        delta = int(off[:2]) * 3600 + int(off[2:]) * 60
        ts -= delta if tz[0] == '+' else -delta
    return ts


def claude_config_file():
    d = os.environ.get('CLAUDE_CONFIG_DIR')
    candidates = ([os.path.join(d, '.claude.json')] if d else []) + [os.path.expanduser('~/.claude.json')]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def scoped_limits():
    """[(label, used_pct, resets_at, window_mins, age_secs)] for every limit in
    the cached snapshot that is scoped to a model or surface."""
    path = claude_config_file()
    if not path:
        return []
    try:
        with open(path, encoding='utf-8') as f:
            snap = json.load(f).get('cachedUsageUtilization') or {}
    except Exception:
        return []
    age = max(0, int(time.time() - (snap.get('fetchedAtMs') or 0) / 1000))
    out = []
    for lim in (snap.get('utilization') or {}).get('limits') or []:
        scope = lim.get('scope') or {}
        name = ((scope.get('model') or {}).get('display_name')
                or (scope.get('surface') or {}).get('display_name'))
        if not name or lim.get('percent') is None:
            continue
        kind = lim.get('kind') or ''
        window = 10080 if kind.startswith('weekly') else 300 if kind.startswith('session') else 0
        out.append((name.lower()[:7], lim['percent'], parse_iso(lim.get('resets_at')), window, age))
    return out


def age_str(secs):
    if secs < STALE_AFTER_SECS:
        return ''
    if secs < 3600:
        return f'{DIM}{secs // 60}m old{RESET}'
    if secs < 86400:
        return f'{DIM}{secs // 3600}h old{RESET}'
    return f'{DIM}{secs // 86400}d old{RESET}'


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

# Any extra window Claude Code starts sending on stdin (e.g. a future
# seven_day_overage_included) is live, so it wins over the cached snapshot.
scoped = scoped_limits()
for key, win in rl.items():
    if key in ('five_hour', 'seven_day', 'spend_limit') or not isinstance(win, dict):
        continue
    if win.get('used_percentage') is None:
        continue
    label = key.replace('seven_day_', '')[:7]
    resets = win.get('resets_at') or 0
    for i, (name, _p, r_at, _w, _a) in enumerate(scoped):
        if resets and abs(r_at - resets) < 120:  # same window → borrow its name
            label = name
            del scoped[i]
            break
    rl_lines.append(limit_line(label, win['used_percentage'], resets, 10080, weekly=True,
                               label_color=PINK))

for name, used, resets, window, age in scoped:
    line = limit_line(name, used, resets, window, weekly=(window != 300), label_color=PINK)
    stale = age_str(age)
    rl_lines.append(line + (' ' + stale if stale else ''))

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

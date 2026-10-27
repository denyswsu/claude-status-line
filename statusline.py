#!/usr/bin/env python3
"""Claude Code status line: model, folder/branch, cost, timer, and a two-column
grid of circle progress bars for context, 5-hour and 7-day rate limits, plus one
bar per model-scoped limit (e.g. Fable) read from Claude Code's usage snapshot.

https://github.com/denyswsu/claude-status-line
"""
import json, sys, subprocess, os, time, re, calendar
from datetime import datetime

# Force UTF-8 output on Windows
sys.stdout.reconfigure(encoding='utf-8', errors='replace')


# ── Optional live refresh of the usage snapshot ──────────────
# Claude Code refreshes its own usage snapshot only at session start and on
# /usage. With CLAUDE_STATUSLINE_FETCH_USAGE=1 this script asks the same
# endpoint itself, at most once a minute, from a detached child process so
# rendering never waits on the network. It uses the OAuth access token Claude
# Code keeps in <config dir>/.credentials.json; the token is sent only to
# api.anthropic.com and never written anywhere. Where the token lives in a
# keychain instead (macOS) there is no file and the refresh stays inactive.
FETCH_EVERY_SECS = 60
USAGE_URL = 'https://api.anthropic.com/api/oauth/usage'


def config_dir():
    return os.environ.get('CLAUDE_CONFIG_DIR') or os.path.expanduser('~/.claude')


def usage_cache_path():
    return os.path.join(config_dir(), 'statusline-usage.json')


def file_age(path):
    try:
        return time.time() - os.path.getmtime(path)
    except OSError:
        return float('inf')


def maybe_refresh_usage():
    if os.environ.get('CLAUDE_STATUSLINE_FETCH_USAGE') != '1':
        return
    cache = usage_cache_path()
    lock = cache + '.lock'
    if file_age(cache) < FETCH_EVERY_SECS or file_age(lock) < 30:
        return
    try:
        with open(lock, 'w'):
            pass
        detach = ({'creationflags': 0x00000008 | 0x00000200} if os.name == 'nt'
                  else {'start_new_session': True})
        subprocess.Popen([sys.executable or 'python3', os.path.abspath(__file__), '--fetch-usage'],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, **detach)
    except Exception:
        pass


def fetch_usage():
    """Child-process mode: one GET, write the cache atomically, exit."""
    import urllib.request
    try:
        with open(os.path.join(config_dir(), '.credentials.json'), encoding='utf-8') as f:
            oauth = json.load(f).get('claudeAiOauth') or {}
        token = oauth.get('accessToken')
        if not token or (oauth.get('expiresAt') or 0) / 1000 < time.time():
            return  # expired: Claude Code renews it on its own; try again next minute
        req = urllib.request.Request(USAGE_URL, headers={
            'Authorization': 'Bearer ' + token,
            'anthropic-beta': 'oauth-2025-04-20',
            'Accept': 'application/json',
            'User-Agent': 'claude-status-line',
        })
        with urllib.request.urlopen(req, timeout=8) as r:
            body = json.load(r)
        cache = usage_cache_path()
        with open(cache + '.tmp', 'w', encoding='utf-8') as f:
            json.dump({'fetchedAtMs': int(time.time() * 1000), 'utilization': body}, f)
        os.replace(cache + '.tmp', cache)
    except Exception:
        pass


if '--fetch-usage' in sys.argv:
    fetch_usage()
    sys.exit(0)

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
    """Ten circles, 5% per step: odd steps show a dimmed filled circle. Only
    ● and ○ are used, since a third glyph such as ◐ often comes from a
    fallback font at a different size."""
    used_pct = max(0, min(100, used_pct))
    halves = int((used_pct * width * 2 + 50) // 100)  # round half up to nearest 5%
    full, half = divmod(halves, 2)
    color = color_for_pct(used_pct)
    out = f'{color}{"●" * full}'
    if half:
        out += f'{RESET}{DIM}{color}●'
    return f'{out}{RESET}{DIM}{"○" * (width - full - half)}{RESET}'


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
    pace = (window_mins - remaining_mins) * 100 // window_mins - int(used_pct)
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
    pct_int = int(used_pct)
    return [
        f'{label_color}{label:<7}{RESET}',
        circle_bar(used_pct),
        f'{color_for_pct(pct_int)}{pct_int:>3d}%{RESET}',
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
# ~/.claude.json (cachedUsageUtilization.utilization.limits[]). That snapshot
# is fetched at session start and when /usage is opened, not continuously, so
# live_estimate() below keeps the bar moving in between.
STALE_AFTER_SECS = 60 * 60


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


def load_snapshot():
    """The newer of Claude Code's own cached snapshot and this script's refresh."""
    snap = {}
    path = claude_config_file()
    if path:
        try:
            with open(path, encoding='utf-8') as f:
                snap = json.load(f).get('cachedUsageUtilization') or {}
        except Exception:
            snap = {}
    try:
        with open(usage_cache_path(), encoding='utf-8') as f:
            ours = json.load(f)
        if (ours.get('fetchedAtMs') or 0) > (snap.get('fetchedAtMs') or 0):
            snap = ours
    except Exception:
        pass
    return snap


def scoped_limits():
    """One dict per limit in the cached snapshot that is scoped to a model or
    surface, plus what is needed to project it forward from live data."""
    snap = load_snapshot()
    if not snap:
        return []
    age = max(0, int(time.time() - (snap.get('fetchedAtMs') or 0) / 1000))
    util = snap.get('utilization') or {}
    weekly0 = (util.get('seven_day') or {}).get('utilization')
    shares = {sh.get('limit_index'): sh for sh in util.get('weekly_scoped_shares') or []
              if isinstance(sh, dict)}
    out = []
    for idx, lim in enumerate(util.get('limits') or []):
        scope = lim.get('scope') or {}
        name = ((scope.get('model') or {}).get('display_name')
                or (scope.get('surface') or {}).get('display_name'))
        if not name or lim.get('percent') is None:
            continue
        kind = lim.get('kind') or ''
        window = 10080 if kind.startswith('weekly') else 300 if kind.startswith('session') else 0
        out.append({
            'name': name.lower(), 'label': name.lower()[:7], 'pct': lim['percent'],
            'resets': parse_iso(lim.get('resets_at')), 'window': window, 'age': age,
            'weekly0': weekly0, 'share': shares.get(idx) if kind.startswith('weekly') else None,
        })
    return out


def live_estimate(lim, weekly_now, model_names):
    """The scoped bucket's growth since the snapshot is not on stdin, but the
    weekly window is. While this session runs that model, growth of the weekly
    number is that model's usage, so project it onto the bucket's allowance
    (weekly_scoped_shares gives the allowance as a share of the weekly budget).
    Returns None when the projection is not possible, e.g. another model."""
    share = lim['share'] or {}
    allowance = share.get('allowance_percent_of_weekly')
    if weekly_now is None or lim['weekly0'] is None or not allowance:
        return None
    if not any(lim['name'] in n for n in model_names):
        return None
    grown = weekly_now - lim['weekly0']
    if grown < 0:  # the weekly window reset after the snapshot was taken
        est = weekly_now * 100 / allowance
    else:
        est = lim['pct'] + grown * 100 / allowance
    return max(0, min(100, est))


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
maybe_refresh_usage()
scoped = scoped_limits()
for key, win in rl.items():
    if key in ('five_hour', 'seven_day', 'spend_limit') or not isinstance(win, dict):
        continue
    if win.get('used_percentage') is None:
        continue
    label = key.replace('seven_day_', '')[:7]
    resets = win.get('resets_at') or 0
    for i, lim in enumerate(scoped):
        if resets and abs(lim['resets'] - resets) < 120:  # same window → borrow its name
            label = lim['label']
            del scoped[i]
            break
    rl_lines.append(limit_line(label, win['used_percentage'], resets, 10080, weekly=True,
                               label_color=PINK))

model_names = [model.lower(), (data.get('model', {}).get('id') or '').lower()]
for lim in scoped:
    est = live_estimate(lim, seven_day.get('used_percentage'), model_names)
    used = lim['pct'] if est is None else est
    line = limit_line(lim['label'], used, lim['resets'], lim['window'],
                      weekly=(lim['window'] != 300), label_color=PINK)
    stale = age_str(lim['age']) if est is None else ''  # a projected bar is not stale
    rl_lines.append(line + (' ' + stale if stale else ''))

# ── Layout: bars two per row, left column padded to align ──
ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')


def visible_len(text):
    return len(ANSI_RE.sub('', text))


def terminal_columns():
    """Best effort. stdout is a pipe here, so ask the controlling tty."""
    env = os.environ.get('COLUMNS', '')
    if env.isdigit() and int(env) > 0:
        return int(env)
    try:
        fd = os.open('/dev/tty', os.O_RDONLY | os.O_NOCTTY)
        try:
            return os.get_terminal_size(fd).columns
        finally:
            os.close(fd)
    except Exception:
        return None


def grid(left, right):
    """Two columns: what is current on the left, the weekly windows on the
    right. Falls back to one cell per row when forced with
    CLAUDE_STATUSLINE_STACKED=1 or when the terminal is known to be too narrow."""
    left_w = max(visible_len(c) for c in left)
    right_w = max((visible_len(c) for c in right), default=0)
    need = left_w + visible_len(SEP) + right_w
    cols = terminal_columns()
    if os.environ.get('CLAUDE_STATUSLINE_STACKED') == '1' or (cols and cols < need):
        return left + right
    out = []
    for i in range(max(len(left), len(right))):
        l = left[i] if i < len(left) else ''
        if i < len(right):
            out.append(l + ' ' * (left_w - visible_len(l)) + SEP + right[i])
        else:
            out.append(l)
    return out


# ── Output ───────────────────────────────────────────────
dur = f'{BCYAN}⏱ {mins}m {secs:02d}s{RESET}'
line1 = f"{BOLD}{PINK}◆ {model}{RESET}{SEP}{AMBER}📁 {dirname}{RESET}{branch}{SEP}{GREEN}${cost:.2f}{RESET}{SEP}{dur}"
if session_name:
    line1 += f"{SEP}{DIM}▸ {session_name}{RESET}"
print(line1)

ctx_parts = row('context', pct)
ctx_parts.append(f'{DIM}{fmt_tokens(ctx_tokens)}/{fmt_tokens(ctx_size)}{RESET}')
for line in grid([' '.join(ctx_parts), rl_lines[0]], rl_lines[1:]):
    print(line)

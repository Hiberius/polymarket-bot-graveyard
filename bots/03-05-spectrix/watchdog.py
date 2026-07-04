#!/usr/bin/env python3
"""
SPECTRIX 2.0 — Watchdog Orchestrator v3
Runs every 5 minutes via launchd. Checks health, auto-fixes, alerts intelligently.

Severity Levels:
  CRITICAL — Bot DOWN, Postgres DOWN, restart failed → always iMessage
  WARNING  — Balance drift, force-close → iMessage once, then 1h cooldown
  INFO     — Expired trades, strategy count → log only, never iMessage

Scheduled Reports:
  3x/day at 08:00, 15:00, 23:00 — bankroll, PnL, positions, strategy status
"""

import asyncio
import math
import subprocess
import json
import urllib.request
import os
import time
from datetime import datetime, timezone, timedelta

import asyncpg

PHONE = os.environ.get("ALERT_PHONE", "")
API_BASE = "http://127.0.0.1:8080"
BOT_DIR = "/Users/calabrofficial/Desktop/SPECTRIX_2_0"
PYTHON = "/opt/homebrew/bin/python3"
LOG_FILE = os.path.join(BOT_DIR, "data", "watchdog.log")
STATE_FILE = "/tmp/spectrix_watchdog_state.json"
HEARTBEAT_FILE = "/tmp/spectrix_watchdog_heartbeat"

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
STALE_HOURS = 30              # force-close after 30h (gives Polymarket time)
WEATHER_STALE_HOURS = 72      # weather uses NOAA (hours-to-days lag) — give 72h
LOSING_MIN_TRADES = 25        # min trades before auto-disable
LOSING_MIN_WR = 0.20          # disable if win rate below 20%
LOSING_WARN_TRADES = 15       # warn (log only) at 15 trades
LOSING_WARN_WR = 0.25         # warn if WR below 25%
BALANCE_DRIFT_THRESHOLD = 100 # alert if balance drifts >$100 from expected
REPORT_HOURS = [8, 15, 23]    # scheduled summary times (local)

# Cooldown: how long (seconds) before re-alerting the same category
COOLDOWN = {
    "critical": 300,     # 5 min — critical issues re-alert fast
    "warning":  3600,    # 1 hour — warnings don't spam
}


# ===========================================================================
# Helpers
# ===========================================================================

def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _sanitize_applescript(text: str) -> str:
    """Strip characters that could break or inject into AppleScript strings."""
    return (text
            .replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("'", "\\'")
            .replace("\n", " | ")
            .replace("\r", ""))


def send_alert(msg):
    """Send iMessage alert. Only called for CRITICAL/WARNING that passed cooldown."""
    if not PHONE:
        log("ALERT SKIPPED: no ALERT_PHONE configured")
        return
    safe_msg = _sanitize_applescript(msg)[:500]  # cap length to avoid huge alerts
    safe_phone = _sanitize_applescript(PHONE)
    try:
        subprocess.run([
            "osascript", "-e",
            f'tell application "Messages" to send "{safe_msg}" to buddy "{safe_phone}" '
            f'of (first account whose service type is iMessage)'
        ], capture_output=True, timeout=10)
        log(f"ALERT SENT: {safe_msg[:120]}")
    except Exception as e:
        log(f"ALERT FAILED: {e}")


def fetch(endpoint):
    try:
        r = urllib.request.urlopen(f"{API_BASE}{endpoint}", timeout=5)
        return json.loads(r.read())
    except Exception:
        return None


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception:
        pass


def write_heartbeat():
    try:
        with open(HEARTBEAT_FILE, "w") as f:
            f.write(str(time.time()))
    except Exception:
        pass


def should_alert(state, category, severity):
    """Check if we should send an iMessage for this category based on cooldown.

    Returns True if cooldown has expired (or no previous alert).
    Always returns False for INFO severity (log only).
    """
    if severity == "info":
        return False

    cooldown_secs = COOLDOWN.get(severity, 3600)
    alert_times = state.get("alert_cooldowns", {})
    last_time = alert_times.get(category, 0)
    return (time.time() - last_time) >= cooldown_secs


def mark_alerted(state, category):
    """Record that we just sent an alert for this category."""
    if "alert_cooldowns" not in state:
        state["alert_cooldowns"] = {}
    state["alert_cooldowns"][category] = time.time()


# ===========================================================================
# Health Checks
# ===========================================================================

def check_bot_alive():
    health = fetch("/health")
    return bool(health and health.get("status") == "ok")


def check_postgres():
    try:
        r = subprocess.run(
            ["/opt/homebrew/opt/postgresql@17/bin/pg_isready"],
            capture_output=True, text=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


def restart_bot():
    log("RESTARTING BOT...")
    subprocess.run(["pkill", "-9", "-f", "python3 -m polybot"],
                   capture_output=True, timeout=5)
    result = subprocess.run(["lsof", "-ti:8080"],
                           capture_output=True, text=True, timeout=5)
    for pid in result.stdout.strip().split("\n"):
        if pid.strip():
            subprocess.run(["kill", "-9", pid.strip()], capture_output=True)
    time.sleep(3)
    subprocess.Popen(
        [PYTHON, "-m", "polybot"],
        cwd=BOT_DIR,
        stdout=open(os.path.join(BOT_DIR, "data", "bot_stdout.log"), "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True)
    log("Bot restarted")


DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql:///polybot")


async def _run_query(sql: str, *args, fetch: bool):
    """Open a short-lived asyncpg connection and run the query.

    We reconnect per call because watchdog runs once every 5 minutes —
    connection pooling would add complexity without meaningful throughput
    gain at this cadence. A timeout of 10s matches the old psql shell-out.
    """
    conn = await asyncpg.connect(DATABASE_URL, timeout=10)
    try:
        if fetch:
            return await conn.fetchval(sql, *args)
        await conn.execute(sql, *args)
        return None
    finally:
        await conn.close()


def db_fetch_val(sql: str, *args):
    """Parameterized SELECT returning a single scalar (fetchval)."""
    try:
        return asyncio.run(_run_query(sql, *args, fetch=True))
    except Exception as e:
        log(f"DB FETCH ERROR: {e}")
        return None


def db_exec(sql: str, *args) -> bool:
    """Parameterized execute for UPDATE/INSERT/DELETE. Returns True on success."""
    try:
        asyncio.run(_run_query(sql, *args, fetch=False))
        return True
    except Exception as e:
        log(f"DB EXEC ERROR: {e}")
        return False


# ===========================================================================
# Checks
# ===========================================================================

def force_close_stale():
    """Force-close trades whose resolution_time passed >STALE_HOURS ago.

    Weather/geopolitics/other slow-resolution markets are handled differently
    from fast-resolution (crypto, sports) markets to avoid the zombie-trade
    bug. Previously, any stale dry_run trade was closed at entry_price with
    pnl=0 and exit_reason='time_stop' — this made weather markets (which
    resolve via NOAA hours-to-days after the forecast period) look like
    perfect zeros in the PnL tally, masking real PnL.

    New behaviour:
      - Weather trades past `WEATHER_STALE_HOURS`: mark status=
        'dry_run_unfilled' with fill_status='unknown'. Refund the deployed
        capital but do NOT record PnL. These trades drop out of the win/loss
        accounting entirely because we can't honestly call them anything.
      - Everything else stale past `STALE_HOURS`: old time_stop behaviour
        (close at entry_price, pnl=0). Still not ideal but it's the honest
        best-effort for markets that should have resolved by now.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=STALE_HOURS)
    weather_cutoff = datetime.now(timezone.utc) - timedelta(hours=WEATHER_STALE_HOURS)

    # ── Weather / NOAA-resolution markets: unfilled, no PnL ──
    weather_count = db_fetch_val(
        "SELECT COUNT(*) FROM trades t JOIN markets m ON t.market_id=m.id "
        "WHERE t.status='dry_run' AND t.strategy='weather' "
        "AND m.resolution_time < $1",
        weather_cutoff,
    ) or 0
    weather_count = int(weather_count)

    weather_size = 0.0
    if weather_count > 0:
        wsize = db_fetch_val(
            "SELECT COALESCE(SUM(t.position_size_usd), 0) FROM trades t "
            "JOIN markets m ON t.market_id=m.id "
            "WHERE t.status='dry_run' AND t.strategy='weather' "
            "AND m.resolution_time < $1",
            weather_cutoff,
        )
        try:
            weather_size = float(wsize) if wsize is not None else 0.0
        except (ValueError, TypeError):
            weather_size = 0.0
        if not math.isfinite(weather_size) or weather_size < 0:
            weather_size = 0.0

        db_exec(
            "UPDATE trades SET status='dry_run_unfilled', "
            "fill_status='unknown', closed_at=NOW() "
            "WHERE status='dry_run' AND strategy='weather' "
            "AND market_id IN (SELECT id FROM markets WHERE resolution_time < $1)",
            weather_cutoff,
        )

        if weather_size > 0:
            db_exec(
                "UPDATE system_state SET bankroll=bankroll+$1, "
                "total_deployed=total_deployed-$1 WHERE id=1",
                weather_size,
            )
        log(f"WEATHER-UNFILLED {weather_count} trades past NOAA window "
            f"(>{WEATHER_STALE_HOURS}h), refunded ${weather_size:.2f} (no PnL)")

    # ── Non-weather stale: legacy time_stop ──
    result = db_fetch_val(
        "SELECT COUNT(*) FROM trades t JOIN markets m ON t.market_id=m.id "
        "WHERE t.status='dry_run' AND t.strategy != 'weather' "
        "AND m.resolution_time < $1",
        cutoff,
    ) or 0
    count = int(result)
    if count == 0:
        return weather_count, weather_size

    size_result = db_fetch_val(
        "SELECT COALESCE(SUM(t.position_size_usd), 0) FROM trades t "
        "JOIN markets m ON t.market_id=m.id "
        "WHERE t.status='dry_run' AND t.strategy != 'weather' "
        "AND m.resolution_time < $1",
        cutoff,
    )
    try:
        total_size = float(size_result) if size_result is not None else 0
    except (ValueError, TypeError):
        total_size = 0
    if not math.isfinite(total_size) or total_size < 0:
        log(f"WARN: invalid total_size={size_result!r}, skipping force-close refund")
        total_size = 0

    db_exec(
        "UPDATE trades SET status='dry_run_resolved', exit_price=entry_price, "
        "pnl=0, adjusted_pnl=0, exit_reason='time_stop', closed_at=NOW() "
        "WHERE status='dry_run' AND strategy != 'weather' "
        "AND market_id IN (SELECT id FROM markets WHERE resolution_time < $1)",
        cutoff,
    )

    if total_size > 0:
        db_exec(
            "UPDATE system_state SET bankroll=bankroll+$1, "
            "total_deployed=total_deployed-$1 WHERE id=1",
            total_size,
        )

    log(f"FORCE-CLOSED {count} stale trades (>{STALE_HOURS}h), refunded ${total_size:.2f}")
    return weather_count + count, weather_size + total_size


def check_losing_strategies():
    """Auto-disable strategies with poor win rate on sufficient sample size.

    As of friction v2.6 the `strategy_performance` table tracks
    `adjusted_pnl`-based wins (a trade is "winning" only if adjusted_pnl > 0
    after slippage, fees, and adverse selection). This check therefore
    already operates on honest, live-equivalent numbers — no gross-pnl
    wins sneak through.

    - Warn (log only) at LOSING_WARN_TRADES trades with < LOSING_WARN_WR
    - Disable at LOSING_MIN_TRADES trades with < LOSING_MIN_WR
    """
    strats = fetch("/strategies")
    if not strats:
        return []

    disabled = []
    for s in strats:
        trades = s.get("total_trades", 0)
        wins = s.get("winning_trades", 0)
        if trades == 0:
            continue

        wr = wins / trades
        # Sanitize strategy name
        strat_name = ''.join(c for c in s.get("strategy", "") if c.isalnum() or c == '_')

        # Auto-disable: 25+ trades, <20% WR
        if trades >= LOSING_MIN_TRADES and wr < LOSING_MIN_WR and s.get("enabled"):
            db_exec(
                "UPDATE strategy_performance SET enabled=false WHERE strategy=$1",
                strat_name,
            )
            disabled.append(f"{strat_name} ({wr*100:.0f}% WR on {trades} trades)")
            log(f"AUTO-DISABLED: {strat_name} — {wr*100:.0f}% win rate on {trades} trades")

        # Warning: 15+ trades, <25% WR (log only, no disable)
        elif trades >= LOSING_WARN_TRADES and wr < LOSING_WARN_WR and s.get("enabled"):
            log(f"WARN: {strat_name} underperforming — {wr*100:.0f}% WR on {trades} trades")

    return disabled


def count_expired_trades(state_data):
    """Count trades past resolution_time but not yet resolved. INFO level only."""
    positions = state_data.get("open_positions", [])
    now = datetime.now(timezone.utc)
    expired = 0
    for p in positions:
        res = p.get("resolution_time", "")
        if res and res not in ("None", "null", ""):
            try:
                rt = datetime.fromisoformat(str(res).replace("Z", "+00:00"))
                if rt < now:
                    expired += 1
            except Exception:
                pass
    return expired


# ===========================================================================
# Scheduled Summary (replaces send_report.py)
# ===========================================================================

def scheduled_summary(state):
    """Send concise status summary 3x/day at REPORT_HOURS."""
    hour = int(time.strftime("%H"))
    if hour not in REPORT_HOURS:
        return

    # Check if already sent this hour
    today_hour = time.strftime("%Y-%m-%d") + f"-{hour:02d}"
    if state.get("last_summary") == today_hour:
        return

    api_state = fetch("/api/state")
    strats = fetch("/strategies")
    if not api_state:
        return

    bankroll = api_state.get("bankroll", 0)
    deployed = api_state.get("total_deployed", 0)
    pnl = api_state.get("daily_pnl", 0)
    positions = api_state.get("open_positions", [])

    # Strategy summary
    enabled = 0
    total_trades = 0
    total_wins = 0
    top_strats = []
    if strats:
        enabled = sum(1 for s in strats if s.get("enabled"))
        for s in sorted(strats, key=lambda x: x.get("total_pnl", 0), reverse=True):
            t = s.get("total_trades", 0)
            w = s.get("winning_trades", 0)
            p = s.get("total_pnl", 0)
            total_trades += t
            total_wins += w
            if t > 0 and len(top_strats) < 3:
                top_strats.append(f"{s['strategy']}:{w}/{t} ${p:.0f}")

    wr = f"{total_wins/total_trades*100:.0f}%" if total_trades > 0 else "-"
    pnl_sign = "+" if pnl >= 0 else ""

    msg = (
        f"SPECTRIX {time.strftime('%H:%M')} | "
        f"${bankroll:.0f} bank | ${deployed:.0f} deploy | "
        f"PnL {pnl_sign}${pnl:.2f} | "
        f"{len(positions)} open | WR {wr} | {enabled} strats"
    )
    if top_strats:
        msg += " | " + " | ".join(top_strats)

    send_alert(msg)
    state["last_summary"] = today_hour
    log(f"SUMMARY sent: {msg[:120]}")


# ===========================================================================
# Main
# ===========================================================================

def main():
    write_heartbeat()
    state = load_state()
    alerts_critical = []
    alerts_warning = []
    info_log = []

    # ------------------------------------------------------------------
    # 1. PostgreSQL (CRITICAL)
    # ------------------------------------------------------------------
    if not check_postgres():
        alerts_critical.append("PostgreSQL DOWN")
        try:
            subprocess.run(
                ["/opt/homebrew/bin/brew", "services", "start", "postgresql@17"],
                capture_output=True, timeout=15)
            time.sleep(3)
            if check_postgres():
                alerts_critical.append("PostgreSQL auto-restarted OK")
            else:
                alerts_critical.append("PostgreSQL restart FAILED")
        except Exception:
            alerts_critical.append("PostgreSQL restart FAILED")

    # ------------------------------------------------------------------
    # 2. Bot alive (CRITICAL)
    # ------------------------------------------------------------------
    if not check_bot_alive():
        alerts_critical.append("Bot DOWN")
        restart_bot()
        time.sleep(10)
        if check_bot_alive():
            alerts_critical.append("Bot auto-restarted OK")
        else:
            alerts_critical.append("Bot restart FAILED")

    # ------------------------------------------------------------------
    # 3. Dashboard API + balance drift
    # ------------------------------------------------------------------
    api_state = fetch("/api/state")
    if not api_state:
        alerts_critical.append("Dashboard API not responding")
    else:
        # Balance drift (WARNING)
        bankroll = api_state.get("bankroll", 0)
        deployed = api_state.get("total_deployed", 0)
        total = bankroll + deployed
        expected_raw = db_fetch_val(
            "SELECT bankroll + total_deployed FROM system_state WHERE id=1")
        try:
            expected = float(expected_raw) if expected_raw is not None else 500.0
        except (ValueError, TypeError):
            expected = 500.0
        if abs(total - expected) > BALANCE_DRIFT_THRESHOLD:
            alerts_warning.append(
                f"Balance drift: ${total:.2f} vs expected ${expected:.2f}")

        # Expired trades (INFO — log only)
        expired = count_expired_trades(api_state)
        if expired > 0:
            info_log.append(f"{expired} trade(s) awaiting Polymarket resolution")

    # ------------------------------------------------------------------
    # 4. Force-close stale positions (WARNING if acted)
    # ------------------------------------------------------------------
    closed_count, closed_size = force_close_stale()
    if closed_count > 0:
        alerts_warning.append(
            f"Force-closed {closed_count} stale trades "
            f"(>{STALE_HOURS}h, ${closed_size:.2f} refunded)")

    # ------------------------------------------------------------------
    # 5. Auto-disable losing strategies (WARNING if acted)
    # ------------------------------------------------------------------
    disabled_strats = check_losing_strategies()
    if disabled_strats:
        alerts_warning.append(
            f"Auto-disabled: {', '.join(disabled_strats)}")

    # ------------------------------------------------------------------
    # 6. Scheduled summary (3x/day)
    # ------------------------------------------------------------------
    try:
        scheduled_summary(state)
    except Exception as e:
        log(f"Summary error: {e}")

    # ------------------------------------------------------------------
    # Send alerts respecting severity + cooldown
    # ------------------------------------------------------------------

    # CRITICAL — always send (with 5 min cooldown to avoid restart loops)
    if alerts_critical:
        if should_alert(state, "critical", "critical"):
            msg = "SPECTRIX CRITICAL: " + " | ".join(alerts_critical)
            send_alert(msg)
            mark_alerted(state, "critical")
        log(f"CRITICAL: {alerts_critical}")

    # WARNING — send once, then 1h cooldown
    if alerts_warning:
        if should_alert(state, "warning", "warning"):
            msg = "SPECTRIX WARNING: " + " | ".join(alerts_warning)
            send_alert(msg)
            mark_alerted(state, "warning")
        log(f"WARNING: {alerts_warning}")

    # INFO — log only, never iMessage
    if info_log:
        log(f"INFO: {' | '.join(info_log)}")

    if not alerts_critical and not alerts_warning and not info_log:
        log("ALL OK")

    save_state(state)


if __name__ == "__main__":
    main()

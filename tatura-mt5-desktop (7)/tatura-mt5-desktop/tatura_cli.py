import signal
import sys
import time

from runner import TaturaBotCoordinator


def main() -> None:
    bot = TaturaBotCoordinator()

    def on_signal(_sig: int, _frame: object) -> None:
        print("\nShutting down Tatura MT5 CLI...")
        bot.stop()
        bot.mt5.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, on_signal)

    print("Connecting to MetaTrader 5...")
    acc = bot.connect_mt5()
    print(f"Connected: #{acc['login']} ({acc['server']}) | Balance: {acc['balance']:.2f} {acc['currency']}")

    print("Syncing with Cloudflare Pages Tatura website...")
    web = bot.sync_website_once()
    print(f"Website GO={web['go']} | Stake=${web['stake_amount']:.2f} ({web['stake_pct']:.1f}%) | Reason: {web['reason']}")

    bot.start()
    last_log_idx = ""
    while True:
        snap = bot.state_snapshot()
        if snap["logs"]:
            top = snap["logs"][0]
            stamp = f"{top['time']}-{top['message']}"
            if stamp != last_log_idx:
                last_log_idx = stamp
                print(f"[{top['time']}] [{top['level']}] {top['message']}")
        time.sleep(1.0)


if __name__ == "__main__":
    main()

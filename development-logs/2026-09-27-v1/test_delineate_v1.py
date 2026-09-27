"""Small reproducible engine matches plus a real stdin/stdout transcript check."""
from pathlib import Path
import importlib.util
import json
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "yk-development-tools"))
sys.path.insert(0, str(ROOT / "bots/delineate_v1"))
from engine.config import load_config
from runner.bots import InProcessBot
from runner.match import run_match


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RecordedBot(InProcessBot):
    def __init__(self, decide):
        self.inputs = []
        self.outputs = []
        self.times = []
        def timed(view, init):
            start = time.perf_counter()
            result = decide(view, init)
            self.times.append((time.perf_counter() - start) * 1000)
            self.outputs.extend(result + ["END"])
            return result
        super().__init__(timed)

    def send_init(self, text):
        self.inputs.append(text)
        super().send_init(text)

    def send_turn(self, text, timeout_s):
        self.inputs.append(text)
        super().send_turn(text, timeout_s)


def main():
    strategy = load("candidate", ROOT / "bots/delineate_v1/main.py")
    sys.path.insert(0, str(ROOT / "yk-python-sample"))
    out = ROOT / "test-results/delineate-v1"
    out.mkdir(parents=True, exist_ok=True)
    results = []
    for level in (1, 2):
        opponent = load("opponent", ROOT / f"yk-python-sample/example_lv{level}.py")
        for seed in (0, 1):
            for team in ("Y", "K"):
                bot = RecordedBot(strategy.Strategy().decide)
                other = InProcessBot(opponent.decide)
                y, k = (bot, other) if team == "Y" else (other, bot)
                replay, result = run_match(seed, load_config(), y, k)
                process = subprocess.run([sys.executable, str(ROOT / "bots/delineate_v1/main.py")],
                                         input="".join(bot.inputs), capture_output=True, text=True, timeout=15)
                assert process.returncode == 0, process.stderr
                assert process.stdout.splitlines() == bot.outputs, "Protocol transcript differs"
                row = {"opponent": f"lv{level}", "team": team, **result,
                       "first_decision_ms": bot.times[0],
                       "max_later_decision_ms": max(bot.times[1:], default=0),
                       "subprocess_transcript_ok": True}
                results.append(row)
                (out / f"lv{level}-seed{seed}-{team}-replay.json").write_text(json.dumps(replay), encoding="utf-8")
                print(json.dumps(row, ensure_ascii=True), flush=True)
    (out / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

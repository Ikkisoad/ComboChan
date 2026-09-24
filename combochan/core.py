"""Small synchronous adapter boundary; inference runs outside frame execution."""
from typing import Protocol

from .bridge import Step, Trial
from .evaluate import evaluate


class SaveStates(Protocol):
    """Opaque full snapshots, including input history and adapter counters."""

    def save_state(self) -> bytes: ...
    def load_state(self, snapshot: bytes) -> None: ...


class GameControl(SaveStates, Protocol):
    """step replaces held buttons and returns a detached observation per frame.

    Observations use the existing evaluator's frame/p1/p2 telemetry schema.
    Unsupported telemetry must not be fabricated by a real adapter.
    """

    def observe(self) -> dict: ...
    def step(self, inputs: Step, defense: str) -> list[dict]: ...
    def release_inputs(self) -> None: ...


class ComboExecutor(Protocol):
    def execute(self, snapshot: bytes, trial: Trial) -> list[dict]: ...


class ResultScorer(Protocol):
    def score(self, record: dict) -> dict: ...


class FrameExecutor:
    def __init__(self, game: GameControl):
        self.game = game

    def execute(self, snapshot: bytes, trial: Trial) -> list[dict]:
        trial.validate()
        records = []
        for repetition in range(1, trial.repeats + 1):
            try:
                self.game.load_state(snapshot)
                trace = [self.game.observe()]
                # Step's per-command bound is smaller than Trial's tail bound.
                tail = trial.tail
                steps = list(trial.steps)
                while tail:
                    frames = min(tail, 240)
                    steps.append(Step(frames))
                    tail -= frames
                for step in steps:
                    rows = self.game.step(step, trial.defense)
                    if len(rows) != step.frames:
                        raise RuntimeError("Adapter returned the wrong frame count")
                    trace.extend(rows)
                start = trace[0]["frame"]
                if [r["frame"] for r in trace] != list(range(start, start + len(trace))):
                    raise RuntimeError("Adapter returned noncontiguous frames")
                # The evaluator consumes trial-relative frame numbers.
                trace = [{**row, "frame": i} for i, row in enumerate(trace)]
                records.append({"id": trial.id, "repetition": repetition,
                                "defense": trial.defense, "trace": trace})
            finally:
                self.game.release_inputs()
        return records


class TelemetryScorer:
    def __init__(self, max_stocks: int | None = 0, require_combo: bool = True):
        self.max_stocks = max_stocks
        self.require_combo = require_combo

    def score(self, record: dict) -> dict:
        return evaluate(record, max_stocks=self.max_stocks,
                        require_combo=self.require_combo)

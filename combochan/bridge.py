"""Bounded, data-only file protocol to the emulator's Lua coroutine."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import hashlib
import json
import os
import time
import uuid

BUTTONS = frozenset("U D L R F B LP MP HP LK MK HK".split())


@dataclass(frozen=True)
class Step:
    frames: int
    buttons: tuple[str, ...] = ()

    def __post_init__(self):
        if type(self.frames) is not int or not 1 <= self.frames <= 240:
            raise ValueError("Step duration must be 1–240 frames")
        if not set(self.buttons) <= BUTTONS or len(set(self.buttons)) != len(self.buttons):
            raise ValueError("Unknown or duplicate buttons")
        if {"L", "R"} <= set(self.buttons) or {"U", "D"} <= set(self.buttons) or {"F", "B"} <= set(self.buttons):
            raise ValueError("Opposing directions")


@dataclass(frozen=True)
class Trial:
    id: str
    steps: tuple[Step, ...]
    repeats: int = 1
    tail: int = 90
    defense: str = "neutral"

    def validate(self):
        if not self.id or not all(c.isascii() and (c.isalnum() or c in "_-") for c in self.id):
            raise ValueError("Invalid trial ID")
        if type(self.repeats) is not int or not 1 <= self.repeats <= 100:
            raise ValueError("Repeats must be 1–100")
        if type(self.tail) is not int or not 1 <= self.tail <= 600:
            raise ValueError("Tail must be 1–600 frames")
        if not self.steps or self.tail + sum(s.frames for s in self.steps) > 1200:
            raise ValueError("Trial must have inputs and at most 1200 frames")
        if self.defense not in ("neutral", "stand", "crouch", "jump"):
            raise ValueError("Invalid defense")


class Bridge:
    def __init__(self, directory: Path, timeout: float = 180, rom: str = "vsavj"):
        self.rom = rom
        self.directory = directory.resolve()
        self.timeout = timeout

    def run(self, trials: list[Trial], speed: str = "turbo") -> tuple[list[dict], dict]:
        if not 1 <= len(trials) <= 512 or len({t.id for t in trials}) != len(trials):
            raise ValueError("Provide 1–512 uniquely named trials")
        if speed not in ("normal", "turbo"):
            raise ValueError("Invalid speed")
        for t in trials:
            t.validate()
        ready_path = self.directory / "ready.json"
        if not ready_path.exists():
            raise RuntimeError("Load bridge/runner.lua in FBNeo first")
        ready = json.loads(ready_path.read_text())
        if ready.get("protocol") != 1 or ready.get("rom") != self.rom:
            raise RuntimeError("Wrong bridge protocol or ROM")
        snapshot = self.directory / "root.fs"
        snapshot_hash = hashlib.sha256(snapshot.read_bytes()).hexdigest()
        job = uuid.uuid4().hex
        lines = [f"COMBOCHAN1\t{job}\troot.fs\t{speed}"]
        for t in trials:
            steps = ";".join(f"{s.frames}:{','.join(s.buttons)}" for s in t.steps)
            lines.append(f"{t.id}\t{t.repeats}\t{t.tail}\t{t.defense}\t{steps}")
        request = self.directory / "request.tsv"
        # Single writer lock; do not overwrite an unconsumed job after timeout.
        lock = self.directory / "client.lock"
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise RuntimeError("Another client owns the bridge; inspect client.lock") from exc
        started = time.monotonic()
        try:
            with os.fdopen(fd, "w") as f:
                f.write(job)
            if request.exists():
                raise RuntimeError("An unconsumed request exists; resume FBNeo before retrying")
            tmp = self.directory / f"{job}.request.tmp"
            tmp.write_text("\n".join(lines) + "\n", encoding="ascii")
            os.replace(tmp, request)
            result = self.directory / f"{job}.jsonl"
            while not result.exists():
                error = self.directory / "error.json"
                if error.exists():
                    raise RuntimeError(error.read_text())
                if time.monotonic() - started > self.timeout:
                    raise TimeoutError(f"Job {job} timed out. Focus/unpause FBNeo; inspect its Lua console. "
                                       "Pending requests/results remain in artifacts/bridge.")
                time.sleep(0.1)
            records = [json.loads(line) for line in result.read_text().splitlines()]
            expected = {(t.id, i, t.defense) for t in trials for i in range(1, t.repeats + 1)}
            received = {(r['id'], r['repetition'], r['defense']) for r in records}
            if received != expected or len(records) != len(expected):
                raise RuntimeError("Incomplete or mismatched emulator results")
            lengths = {t.id: 1+t.tail+sum(s.frames for s in t.steps) for t in trials}
            if any(len(r["trace"]) != lengths[r["id"]] for r in records):
                raise RuntimeError("Emulator did not execute the requested frame count")
            manifest = {"job": job, "snapshot_sha256": snapshot_hash, "rom": ready['rom'],
                        "adapter_sha256": hashlib.sha256(ready["script_content"].encode("utf-8") if "script_content" in ready else Path(ready["script"]).read_bytes()).hexdigest(),
                        "speed": speed, "wall_seconds": time.monotonic() - started,
                        "trials": [asdict(t) for t in trials], "raw_results": str(result)}
            (self.directory / f"{job}.manifest.json").write_text(json.dumps(manifest, indent=2))
            return records, manifest
        finally:
            lock.unlink(missing_ok=True)

"""Bounded, data-only file protocol to the emulator's Lua coroutine."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import hashlib
import json
import os
import re
import time
import uuid

BUTTONS = frozenset("U D L R F B LP MP HP LK MK HK A1 A2".split())


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
    checkpoint_steps: int = 0

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
        if type(self.checkpoint_steps) is not int or not 0 <= self.checkpoint_steps < len(self.steps):
            raise ValueError("Checkpoint must precede a continuation step")


class Bridge:
    def __init__(self, directory: Path, timeout: float = 180, rom: str = "vsavj", snapshot: str = "root.fs"):
        if not re.fullmatch(r"[A-Za-z0-9_-]+\.(?:fs|state)", snapshot):
            raise ValueError("Invalid snapshot filename")
        self.snapshot = snapshot
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
            raise RuntimeError("Connect the prepared emulator runner first")
        ready = json.loads(ready_path.read_text())
        if ready.get("protocol") != 1 or ready.get("rom") != self.rom:
            raise RuntimeError("Wrong bridge protocol or ROM")
        snapshot = self.directory / self.snapshot
        snapshot_hash = hashlib.sha256(snapshot.read_bytes()).hexdigest()
        job = uuid.uuid4().hex
        lines = [f"COMBOCHAN1\t{job}\t{self.snapshot}\t{speed}"]
        for t in trials:
            steps = ";".join(f"{s.frames}:{','.join(s.buttons)}" for s in t.steps)
            line=f"{t.id}\t{t.repeats}\t{t.tail}\t{t.defense}\t{steps}"
            if ready.get('prefix_checkpoints') and speed=='turbo' and t.defense=='neutral':
                line+=f"\t{t.checkpoint_steps}"
            lines.append(line)
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
                raise RuntimeError("An unconsumed request exists; resume the emulator before retrying")
            tmp = self.directory / f"{job}.request.tmp"
            tmp.write_text("\n".join(lines) + "\n", encoding="ascii")
            os.replace(tmp, request)
            result = self.directory / f"{job}.jsonl"
            while not result.exists():
                error = self.directory / "error.json"
                if error.exists():
                    raise RuntimeError(error.read_text())
                if time.monotonic() - started > self.timeout:
                    raise TimeoutError(f"Job {job} timed out. Unpause the emulator; inspect the session error file. "
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
                        "profile_sha256": ready.get("profile_sha256"),
                        "adapter_sha256": hashlib.sha256(ready["script_content"].encode("utf-8") if "script_content" in ready else Path(ready["script"]).read_bytes()).hexdigest(),
                        "speed": speed, "actual_speed": ready.get("actual_speed", speed),
                        "backend": ready.get("backend", "fbneo"), "wall_seconds": time.monotonic() - started,
                        "checkpoint_frames_reused": sum(r.get('checkpoint_frames',0) for r in records),
                        "trials": [asdict(t) for t in trials], "raw_results": str(result)}
            (self.directory / f"{job}.manifest.json").write_text(json.dumps(manifest, indent=2))
            return records, manifest
        finally:
            lock.unlink(missing_ok=True)


class BridgePool:
    """Execute independent trials concurrently, preserving caller order and evidence."""

    def __init__(self, bridges):
        if not bridges:
            raise ValueError('At least one emulator bridge is required')
        self.bridges = bridges

    def _run(self, assignments, speed):
        started = time.monotonic()
        # Wait for every submitted batch even on failure so cancellation/failure
        # cannot leave an untracked client writing to a session.
        with ThreadPoolExecutor(max_workers=len(assignments)) as executor:
            futures = [executor.submit(bridge.run, trials, speed) for bridge, trials in assignments]
            results = [future.result() for future in futures]
        if len(results) == 1:
            return results[0]
        records = [record for rows, _ in results for record in rows]
        manifests = [manifest for _, manifest in results]
        for key in ('snapshot_sha256', 'rom', 'profile_sha256', 'adapter_sha256'):
            if any(m.get(key) != manifests[0].get(key) for m in manifests):
                raise RuntimeError('Emulator instances returned different snapshot or adapter identities')
        manifest = {key: value for key, value in manifests[0].items()
                    if key not in ('job', 'raw_results', 'trials', 'wall_seconds')}
        manifest.update(worker_manifests=manifests, wall_seconds=time.monotonic()-started,
                        checkpoint_frames_reused=sum(m.get('checkpoint_frames_reused',0) for m in manifests),
                        trials=[trial for m in manifests for trial in m['trials']])
        return records, manifest

    def run(self, trials, speed='turbo'):
        if not 1 <= len(trials) <= 512 or len({t.id for t in trials}) != len(trials):
            raise ValueError('Provide 1–512 uniquely named trials')
        if speed not in ('normal', 'turbo'):
            raise ValueError('Invalid speed')
        for trial in trials:
            trial.validate()
        count = min(len(trials), len(self.bridges))
        records, manifest = self._run([(bridge, trials[i::count])
                                       for i, bridge in enumerate(self.bridges[:count])], speed)
        order = {trial.id: i for i, trial in enumerate(trials)}
        records.sort(key=lambda row: (order[row['id']], row['repetition']))
        return records, manifest

    def run_all(self, trials):
        """Check restoration on every instance, including consistency across them."""
        return self._run([(bridge, trials) for bridge in self.bridges], 'turbo')

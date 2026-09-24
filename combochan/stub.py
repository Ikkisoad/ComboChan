"""Deterministic toy combat, not a simulation or validation of Vampire Savior."""
import json

from .bridge import Step


class StubAdapter:
    def __init__(self):
        self.frame = 0
        self.health = 288
        self.stun = 0
        self.hits = 0
        self.held = ()

    def save_state(self) -> bytes:
        return json.dumps({"version": 1, "frame": self.frame, "health": self.health,
                           "stun": self.stun, "hits": self.hits,
                           "held": self.held}, sort_keys=True).encode()

    def load_state(self, snapshot: bytes) -> None:
        state = json.loads(snapshot)
        if state["version"] != 1:
            raise ValueError("Unsupported stub snapshot")
        self.frame = state["frame"]
        self.health = state["health"]
        self.stun = state["stun"]
        self.hits = state["hits"]
        self.held = tuple(state["held"])

    def observe(self) -> dict:
        player = {"health": 288, "recoverable": 288, "stocks": 0,
                  "stun1": 0, "stun2": 0, "combo_hits": 0}
        return {"frame": self.frame, "p1": player,
                "p2": {**player, "health": self.health,
                       "recoverable": self.health, "stun1": self.stun,
                       "combo_hits": self.hits}}

    def step(self, inputs: Step, defense: str = "neutral") -> list[dict]:
        if defense not in ("neutral", "stand", "crouch", "jump"):
            raise ValueError("Invalid defense")
        rows = []
        for _ in range(inputs.frames):
            connected = self.stun > 0
            self.frame += 1
            self.stun = max(0, self.stun - 1)
            if not connected:
                self.hits = 0
            pressed = set(inputs.buttons) - set(self.held)
            damage = max((amount for button, amount in (("LP", 5), ("MP", 10), ("HK", 15))
                          if button in pressed), default=0)
            if damage and (connected or defense == "neutral"):
                self.health = max(0, self.health - damage)
                self.stun = 12
                self.hits += 1
            self.held = tuple(inputs.buttons)
            rows.append(self.observe())
        return rows

    def release_inputs(self) -> None:
        self.held = ()

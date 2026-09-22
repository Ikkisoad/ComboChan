"""Candidate ordering only: model scores never certify combo validity."""
import json
import os
from pathlib import Path
import random
import time


class Policy:
    def __init__(self, mode="heuristic", seed=0, model: Path | None = None):
        self.mode = mode
        self.rng = random.Random(seed)
        self.calls = []
        self.model_info = None
        if mode == "laya":
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
            import torch
            import laya
            torch.set_num_threads(min(8, os.cpu_count() or 1))
            if model is None or not (model / "combochan-model.json").exists():
                raise RuntimeError("Run python -m combochan.download_model first")
            self.model_info = json.loads((model / "combochan-model.json").read_text())
            started = time.monotonic()
            self.agent = laya.load(str(model.resolve()))
            self.model_info.update(package=laya.__version__, device=str(self.agent.device),
                                   load_seconds=time.monotonic()-started)

    def order(self, candidates, context):
        candidates = list(candidates)
        if self.mode == "random":
            self.rng.shuffle(candidates)
        elif self.mode == "laya" and len(candidates) > 1:
            # Rank small groups to fit the model's option/context budget. Rotate groups
            # with a seeded shuffle, and retain every candidate for exploration.
            self.rng.shuffle(candidates)
            ranked = []
            for offset in range(0, len(candidates), 12):
                group = candidates[offset:offset+12]
                if len(group) == 1:
                    ranked.extend(group)
                    continue
                options = {str(i): c["label"] for i, c in enumerate(group)}
                question = {"next": {"type": "choice", "instructions":
                    "Which next experiment is most likely to extend a true meterless combo in Vampire Savior? "
                    "Choose a continuation; short delays may cancel, long delays may drop the combo.",
                    "criteria": options}}
                start = time.monotonic()
                response = self.agent.predict(context, question)
                probabilities = response["answers"]["next"]["probabilities"]
                self.calls.append({"seconds": time.monotonic()-start, "context": context,
                                   "options": options, "response": response})
                ordered = sorted(enumerate(group), key=lambda pair: -probabilities[str(pair[0])])
                # One random exploration candidate per group avoids model-only ranking.
                explore = self.rng.randrange(len(ordered))
                ordered.insert(1, ordered.pop(explore))
                ranked.extend(item for _, item in ordered)
            # Interleave groups so the first batch is not the only one explored.
            candidates = [c for row in zip(*[ranked[i:i+12] for i in range(0,len(ranked),12)]) for c in row] if len(ranked)%12==0 else ranked
        return candidates

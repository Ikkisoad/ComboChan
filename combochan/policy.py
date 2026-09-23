"""Candidate ordering only: model scores never certify combo validity."""
import json
import os
from pathlib import Path
import random
import time
import threading


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

    def guided_batch(self, candidates, context, size=16, progress=None, check_cancel=None):
        """One inference on at most 12 choices, then return actual trials immediately."""
        if check_cancel: check_cancel()
        window=candidates[:64]
        count=min(12,len(window))
        if count<2: return list(candidates[:size])
        indexes=[i*(len(window)-1)//(count-1) for i in range(count)]
        group=[window[i] for i in indexes]
        options={str(i):c.get('notation',c['label']) for i,c in enumerate(group)}
        question={'next':{'type':'choice','instructions':
            'Choose the continuation most likely to extend the combo under the supplied game and resource rules. Consider timing, landing, and available resources.',
            'criteria':options}}
        started=time.monotonic();done=threading.Event()
        def report():
            if progress: progress(len(group),time.monotonic()-started,len(self.calls))
        def heartbeat():
            while not done.wait(2): report()
        report()
        thread=threading.Thread(target=heartbeat,daemon=True);thread.start()
        try: response=self.agent.predict(context,question)
        finally: done.set();thread.join()
        probabilities=response['answers']['next']['probabilities']
        self.calls.append({'seconds':time.monotonic()-started,'context':context,'options':options,'response':response})
        if check_cancel: check_cancel()
        ranked=sorted(enumerate(group),key=lambda pair:-probabilities[str(pair[0])])
        selected=[c for _,c in ranked[:min(8,size)]]
        selected_ids={id(c) for c in selected}
        # Keep baseline exploration; defer the remaining options without losing them.
        for candidate in candidates:
            if len(selected)>=size: break
            if id(candidate) not in selected_ids:
                selected.append(candidate);selected_ids.add(id(candidate))
        return selected

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
                    "Which next experiment is most likely to extend a combo under the supplied game and resource rules? "
                    "Consider the current position, available resources, and air-to-ground transitions. Delays may allow landing or recovery; excessive delays may drop the combo.",
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

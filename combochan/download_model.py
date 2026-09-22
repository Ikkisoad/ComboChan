"""Explicit one-time model download; inference afterwards is local only."""
from pathlib import Path
import json
import os


def main():
    from huggingface_hub import HfApi, snapshot_download
    root = Path(__file__).resolve().parents[1]
    os.environ.setdefault("HF_HOME", str(root / "models" / "cache"))
    repo = "convaiinnovations/laya"
    revision = HfApi().model_info(repo).sha
    path = root / "models" / "laya"
    snapshot_download(repo, revision=revision, local_dir=path,
                      allow_patterns=["model.safetensors", "rl_agent_config.json", "encoder/*", "tokenizer/*", "LICENSE*"])
    (path / "combochan-model.json").write_text(json.dumps({"repo": repo, "revision": revision}, indent=2))
    print(f"Pinned {repo}@{revision} in {path}")


if __name__ == "__main__":
    main()

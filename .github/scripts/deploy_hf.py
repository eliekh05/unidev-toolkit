"""
deploy_hf.py — called by ci.yml to push this repo to a Hugging Face Space.

Required environment variables (set as GitHub Actions secrets):
  HF_TOKEN  — Hugging Face write token  (hf_…)
  HF_SPACE  — Space repo id             (username/spacename)
"""
import os
import sys

hf_token = os.environ.get("HF_TOKEN", "")
hf_space = os.environ.get("HF_SPACE", "")

if not hf_token or not hf_space:
    print("::warning::HF_TOKEN or HF_SPACE not set — skipping Hugging Face deploy")
    sys.exit(0)

from huggingface_hub import HfApi

sha = os.environ.get("GITHUB_SHA", "")[:8]

api = HfApi(token=hf_token)
api.upload_folder(
    folder_path=".",
    repo_id=hf_space,
    repo_type="space",
    ignore_patterns=[
        ".git",
        ".github",
        "node_modules",
        "frontend/node_modules",
        "__pycache__",
        "*.pyc",
        "frontend/dist",
        ".venv",
        "*.egg-info",
    ],
    commit_message=f"Deploy from GitHub Actions — {sha}",
)
print(f"Deployed to Hugging Face Space: {hf_space}")

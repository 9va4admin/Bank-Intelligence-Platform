"""Train the SYNTHETIC STAND-IN fraud model (plumbing proof only — NOT real fraud detection).

Usage:  python scripts/train_standin_fraud_model.py [models/fraud_standin.json]
Then set the Layer 3 config key  cts.fraud_model_path  to that file and restart the worker.
Replace with a model trained on real labelled cheques before relying on fraud scores.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from modules.cts.fraud_model import train_standin_model  # noqa: E402

out = sys.argv[1] if len(sys.argv) > 1 else "models/fraud_standin.json"
os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
train_standin_model(out)
print("wrote", out, "(synthetic stand-in)")

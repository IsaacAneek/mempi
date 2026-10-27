#!/usr/bin/env python3
"""
inference.py - Multi-Model Inference & Latency Prediction Engine
================================================================
Performs inference using trained models (Random Forest, Gradient Boosting,
Extra Trees, Ridge, SVR) to predict GPU interference slowdown and latency.

Usage:
  # Predict for an experiment from dataset:
  python3 inference.py --experiment 64mw_rnd

  # Predict for all test samples comparing all models:
  python3 inference.py --compare-all

  # Predict using a custom input CSV of counters:
  python3 inference.py --input-csv custom_sample.csv --model models/mempi_gradient_boosting_model.pkl
"""

import os
import sys
import glob
import json
import argparse
import joblib
import numpy as np
import pandas as pd

MODELS_DIR = "models"
DATASET_PATH = "dataset.csv"
BASELINE_LATENCY_MS = 4116.0  # Measured baseline latency in ms


def find_available_models(models_dir=MODELS_DIR):
    if not os.path.exists(models_dir):
        # Fallback to root pkl files
        root_models = glob.glob("*.pkl")
        return {os.path.splitext(os.path.basename(m))[0]: m for m in root_models}
    
    model_files = glob.glob(os.path.join(models_dir, "*.pkl"))
    models = {}
    for mf in model_files:
        name = os.path.basename(mf).replace("mempi_", "").replace("_model.pkl", "").replace(".pkl", "")
        models[name] = mf
    return models


def load_model(model_path):
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Model file '{model_path}' not found!")
    return joblib.load(model_path)


def run_inference(model, features_df, baseline_ms=BASELINE_LATENCY_MS):
    preds_slowdown = model.predict(features_df)
    preds_latency = preds_slowdown * baseline_ms
    return preds_slowdown, preds_latency


def main():
    parser = argparse.ArgumentParser(description="MemPi Multi-Model Inference Engine")
    parser.add_argument("--model", default="all", help="Path to model file or 'all'")
    parser.add_argument("--experiment", default=None, help="Experiment name from dataset.csv (e.g. 64mw_rnd)")
    parser.add_argument("--input-csv", default=None, help="CSV file containing V3D counter feature columns")
    parser.add_argument("--dataset", default=DATASET_PATH, help="Path to dataset.csv")
    parser.add_argument("--compare-all", action="store_true", help="Run side-by-side comparison across all models on sample data")
    parser.add_argument("--baseline-ms", type=float, default=BASELINE_LATENCY_MS, help="Baseline GPU latency in ms")
    args = parser.parse_args()

    models_available = find_available_models()
    if not models_available:
        print("No trained models found! Please run 'python3 train_models.py' first.")
        sys.exit(1)

    # Determine input features
    df_raw = None
    if args.input_csv:
        df_raw = pd.read_csv(args.input_csv)
        meta_cols = ["experiment", "e2e_latency_ms", "slowdown"]
        feature_cols = [c for c in df_raw.columns if c not in meta_cols]
        X = df_raw[feature_cols]
        exp_labels = df_raw["experiment"] if "experiment" in df_raw.columns else [f"sample_{i}" for i in range(len(df_raw))]
    elif args.experiment:
        df_dataset = pd.read_csv(args.dataset)
        match = df_dataset[df_dataset["experiment"] == args.experiment]
        if match.empty:
            print(f"Error: Experiment '{args.experiment}' not found in '{args.dataset}'.")
            sys.exit(1)
        meta_cols = ["experiment", "e2e_latency_ms", "slowdown"]
        feature_cols = [c for c in df_dataset.columns if c not in meta_cols]
        X = match[feature_cols]
        exp_labels = match["experiment"]
        df_raw = match
    else:
        # Default: sample representative scenarios (baseline, cache, dram, pagefault, cpu)
        df_dataset = pd.read_csv(args.dataset)
        sample_exps = ["16kr", "1mr", "4mr", "8mr", "64mw_rnd", "mutex1_t4", "ng_fault_t4"]
        match = df_dataset[df_dataset["experiment"].isin(sample_exps)]
        meta_cols = ["experiment", "e2e_latency_ms", "slowdown"]
        feature_cols = [c for c in df_dataset.columns if c not in meta_cols]
        X = match[feature_cols]
        exp_labels = match["experiment"]
        df_raw = match

    print("\n" + "=" * 90)
    print("MEMPI MULTI-MODEL INFERENCE PIPELINE")
    print("=" * 90)
    print(f"Evaluating {len(X)} sample(s) with {len(feature_cols)} hardware counter features.")
    print(f"Baseline reference latency: {args.baseline_ms:.2f} ms\n")

    models_to_run = {}
    if args.model == "all" or args.compare_all:
        for m_name, m_path in models_available.items():
            models_to_run[m_name] = load_model(m_path)
    else:
        # Single model specified by path or alias
        if os.path.exists(args.model):
            m_path = args.model
            m_name = os.path.splitext(os.path.basename(m_path))[0]
        elif args.model in models_available:
            m_path = models_available[args.model]
            m_name = args.model
        else:
            print(f"Error: Model '{args.model}' not found. Available: {list(models_available.keys())}")
            sys.exit(1)
        models_to_run[m_name] = load_model(m_path)

    # Perform inference and print report
    for exp_idx, (_, row) in enumerate(X.iterrows()):
        exp_name = exp_labels.iloc[exp_idx]
        actual_slowdown = df_raw.iloc[exp_idx]["slowdown"] if "slowdown" in df_raw.columns else None
        actual_latency = df_raw.iloc[exp_idx]["e2e_latency_ms"] if "e2e_latency_ms" in df_raw.columns else None

        print(f"--- Target Experiment: {exp_name} ---")
        if actual_slowdown is not None:
            print(f"  Ground Truth: Slowdown = {actual_slowdown:.3f}x | E2E Latency = {actual_latency:.2f} ms")

        print(f"  {'Model':<25} {'Pred Slowdown':<15} {'Pred Latency (ms)':<20} {'Error (%)':<10}")
        print("  " + "-" * 72)

        for m_name, model in models_to_run.items():
            sample_df = pd.DataFrame([row])
            s_pred, l_pred = run_inference(model, sample_df, baseline_ms=args.baseline_ms)
            s_val = s_pred[0]
            l_val = l_pred[0]

            err_str = "N/A"
            if actual_slowdown is not None:
                err_pct = abs(s_val - actual_slowdown) / actual_slowdown * 100
                err_str = f"{err_pct:.2f}%"

            print(f"  {m_name:<25} {s_val:10.3f}x {l_val:16.2f} ms {err_str:>10}")
        print()

    print("=" * 90 + "\n")


if __name__ == "__main__":
    main()


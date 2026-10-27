#!/usr/bin/env python3
"""
train_models.py - Multi-Model Training, Benchmarking, and Evaluation Pipeline
=============================================================================
Trains and evaluates multiple regression models to predict GPU slowdown and
end-to-end latency from V3D hardware performance counters on Raspberry Pi 5.

Features:
  - Train/Validation/Test split (70% Train, 15% Validation, 15% Test)
  - Models: Random Forest, Gradient Boosting, Extra Trees, Ridge Linear, SVR
  - Preprocessing pipelines (StandardScaler for linear & kernel methods)
  - Benchmarks: R2, RMSE, MAE, Training Time (ms), Inference Latency (us/sample)
  - Artifact export: Serializes models, metrics (CSV/JSON), and predictions
"""

import os
import sys
import json
import time
import argparse
import joblib
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor, ExtraTreesRegressor
from sklearn.linear_model import Ridge
from sklearn.svm import SVR
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import r2_score, mean_squared_error, mean_absolute_error, max_error

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))

# Resolve dataset location
CANDIDATE_DATASETS = [
    os.path.join(REPO_ROOT, "ml", "dataset", "dataset.csv"),
    os.path.join(SCRIPT_DIR, "..", "dataset", "dataset.csv"),
    os.path.join(SCRIPT_DIR, "dataset.csv"),
    "dataset.csv"
]
DEFAULT_DATASET = next((p for p in CANDIDATE_DATASETS if os.path.exists(p)), CANDIDATE_DATASETS[0])

DEFAULT_MODELS_DIR = os.path.join(SCRIPT_DIR, "models")
DEFAULT_OUTPUT_CSV = os.path.join(SCRIPT_DIR, "model_benchmark_results.csv")
DEFAULT_OUTPUT_JSON = os.path.join(SCRIPT_DIR, "model_benchmark_results.json")


def load_dataset(csv_path=DEFAULT_DATASET):
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Dataset '{csv_path}' not found!")
    df = pd.read_csv(csv_path)
    
    target_col = "slowdown"
    meta_cols = ["experiment", "e2e_latency_ms", "slowdown"]
    feature_cols = [c for c in df.columns if c not in meta_cols]
    
    X = df[feature_cols]
    y = df[target_col]
    experiments = df["experiment"]
    e2e_lat = df["e2e_latency_ms"]
    
    return df, X, y, feature_cols, experiments, e2e_lat


def split_data(X, y, experiments, e2e_lat, train_ratio=0.70, val_ratio=0.15, test_ratio=0.15, random_state=42):
    assert np.isclose(train_ratio + val_ratio + test_ratio, 1.0)
    
    # First split: Train vs Temp (Val + Test)
    temp_ratio = val_ratio + test_ratio
    X_train, X_temp, y_train, y_temp, exp_train, exp_temp, e2e_train, e2e_temp = train_test_split(
        X, y, experiments, e2e_lat, test_size=temp_ratio, random_state=random_state
    )
    
    # Second split: Val vs Test
    test_sub_ratio = test_ratio / temp_ratio
    X_val, X_test, y_val, y_test, exp_val, exp_test, e2e_val, e2e_test = train_test_split(
        X_temp, y_temp, exp_temp, e2e_temp, test_size=test_sub_ratio, random_state=random_state
    )
    
    split_info = {
        "train_samples": len(X_train),
        "val_samples": len(X_val),
        "test_samples": len(X_test),
        "total_samples": len(X),
        "train_pct": len(X_train) / len(X) * 100,
        "val_pct": len(X_val) / len(X) * 100,
        "test_pct": len(X_test) / len(X) * 100
    }
    
    splits = {
        "X_train": X_train, "y_train": y_train, "exp_train": exp_train, "e2e_train": e2e_train,
        "X_val": X_val,     "y_val": y_val,     "exp_val": exp_val,     "e2e_val": e2e_val,
        "X_test": X_test,   "y_test": y_test,   "exp_test": exp_test,   "e2e_test": e2e_test,
    }
    return splits, split_info


def get_models(random_state=42):
    return {
        "Random Forest": {
            "model": RandomForestRegressor(
                n_estimators=100,
                max_depth=None,
                min_samples_split=2,
                min_samples_leaf=1,
                random_state=random_state
            ),
            "type": "Ensemble (Bagging of Decision Trees)",
            "params": {"n_estimators": 100, "criterion": "squared_error", "max_depth": "None", "random_state": random_state}
        },
        "Gradient Boosting": {
            "model": GradientBoostingRegressor(
                n_estimators=100,
                learning_rate=0.1,
                max_depth=3,
                random_state=random_state
            ),
            "type": "Ensemble (Sequential Gradient Boosted Trees)",
            "params": {"n_estimators": 100, "learning_rate": 0.1, "max_depth": 3, "loss": "squared_error", "random_state": random_state}
        },
        "Extra Trees": {
            "model": ExtraTreesRegressor(
                n_estimators=100,
                max_depth=None,
                random_state=random_state
            ),
            "type": "Ensemble (Extremely Randomized Trees)",
            "params": {"n_estimators": 100, "criterion": "squared_error", "max_depth": "None", "random_state": random_state}
        },
        "Ridge Linear": {
            "model": Pipeline([
                ("scaler", StandardScaler()),
                ("regressor", Ridge(alpha=1.0))
            ]),
            "type": "L2 Regularized Linear Regression",
            "params": {"alpha": 1.0, "solver": "auto", "preprocessing": "StandardScaler"}
        },
        "SVR (RBF Kernel)": {
            "model": Pipeline([
                ("scaler", StandardScaler()),
                ("regressor", SVR(kernel="rbf", C=10.0, epsilon=0.05))
            ]),
            "type": "Support Vector Regression with RBF Kernel",
            "params": {"kernel": "rbf", "C": 10.0, "epsilon": 0.05, "preprocessing": "StandardScaler"}
        }
    }


def compute_metrics(y_true, y_pred):
    r2 = r2_score(y_true, y_pred)
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))
    mae = mean_absolute_error(y_true, y_pred)
    max_e = max_error(y_true, y_pred)
    mape = np.mean(np.abs((y_true - y_pred) / y_true)) * 100
    return {
        "R2": float(r2),
        "RMSE": float(rmse),
        "MAE": float(mae),
        "MaxError": float(max_e),
        "MAPE_pct": float(mape)
    }


def train_and_benchmark(splits, random_state=42, export_dir=DEFAULT_MODELS_DIR):
    os.makedirs(export_dir, exist_ok=True)
    models_dict = get_models(random_state)
    
    X_train, y_train = splits["X_train"], splits["y_train"]
    X_val, y_val = splits["X_val"], splits["y_val"]
    X_test, y_test = splits["X_test"], splits["y_test"]
    
    results = []
    trained_instances = {}
    
    print("\n" + "=" * 80)
    print("TRAINING AND BENCHMARKING MULTIPLE MODELS")
    print("=" * 80)
    
    for name, config in models_dict.items():
        estimator = config["model"]
        
        # 1. Training benchmark
        t_start = time.perf_counter()
        estimator.fit(X_train, y_train)
        fit_time_ms = (time.perf_counter() - t_start) * 1000
        
        # 2. Inference latency benchmark (warmup then multiple repetitions on test set)
        _ = estimator.predict(X_test)
        reps = 50
        t0 = time.perf_counter()
        for _ in range(reps):
            test_preds = estimator.predict(X_test)
        total_inf_time = (time.perf_counter() - t0)
        inf_latency_us = (total_inf_time / (reps * len(X_test))) * 1e6
        
        # 3. Predict on all splits
        train_preds = estimator.predict(X_train)
        val_preds = estimator.predict(X_val)
        
        # 4. Metrics
        m_train = compute_metrics(y_train, train_preds)
        m_val = compute_metrics(y_val, val_preds)
        m_test = compute_metrics(y_test, test_preds)
        
        # 5. Save model artifact
        slug = name.lower().replace(" ", "_").replace("(", "").replace(")", "").replace("-", "_")
        filename = f"mempi_{slug}_model.pkl"
        filepath = os.path.join(export_dir, filename)
        joblib.dump(estimator, filepath)
        
        # Keep local mempi_rf_model.pkl updated
        if "Random Forest" in name:
            joblib.dump(estimator, os.path.join(SCRIPT_DIR, "mempi_rf_model.pkl"))
            
        trained_instances[name] = estimator
        
        row = {
            "Model": name,
            "Architecture": config["type"],
            "Fit Time (ms)": round(fit_time_ms, 2),
            "Inf Latency (us/sample)": round(inf_latency_us, 2),
            "Train R2": round(m_train["R2"], 4),
            "Train RMSE": round(m_train["RMSE"], 4),
            "Train MAE": round(m_train["MAE"], 4),
            "Val R2": round(m_val["R2"], 4),
            "Val RMSE": round(m_val["RMSE"], 4),
            "Val MAE": round(m_val["MAE"], 4),
            "Test R2": round(m_test["R2"], 4),
            "Test RMSE": round(m_test["RMSE"], 4),
            "Test MAE": round(m_test["MAE"], 4),
            "Test MAPE (%)": round(m_test["MAPE_pct"], 2),
            "Artifact": filepath,
            "Parameters": config["params"]
        }
        results.append(row)
        
        print(f"[{name:<18}] Fit: {fit_time_ms:6.2f} ms | Inf: {inf_latency_us:6.2f} us/smp | "
              f"Test R2: {m_test['R2']:.4f} | RMSE: {m_test['RMSE']:.4f} | MAE: {m_test['MAE']:.4f}")
        
    print("=" * 80 + "\n")
    return results, trained_instances


def save_reports(results, split_info, feature_cols, output_csv=DEFAULT_OUTPUT_CSV, output_json=DEFAULT_OUTPUT_JSON):
    df_results = pd.DataFrame(results)
    
    # Save CSV summary
    summary_cols = [
        "Model", "Architecture", "Fit Time (ms)", "Inf Latency (us/sample)",
        "Train R2", "Val R2", "Test R2",
        "Train RMSE", "Val RMSE", "Test RMSE",
        "Train MAE", "Val MAE", "Test MAE", "Test MAPE (%)", "Artifact"
    ]
    df_results[summary_cols].to_csv(output_csv, index=False)
    
    # Save JSON summary with full metadata
    report = {
        "execution_date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "split_summary": split_info,
        "input_features_count": len(feature_cols),
        "input_features": feature_cols,
        "models": results
    }
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        
    print(f"Results successfully saved to '{output_csv}' and '{output_json}'.")


def main():
    parser = argparse.ArgumentParser(description="MemPi Multi-Model Trainer & Benchmarker")
    parser.add_argument("--dataset", default=DEFAULT_DATASET, help=f"Path to input dataset.csv (default: {DEFAULT_DATASET})")
    parser.add_argument("--export-dir", default=DEFAULT_MODELS_DIR, help=f"Directory to save serialized models (default: {DEFAULT_MODELS_DIR})")
    parser.add_argument("--output-csv", default=DEFAULT_OUTPUT_CSV, help=f"Output CSV path (default: {DEFAULT_OUTPUT_CSV})")
    parser.add_argument("--output-json", default=DEFAULT_OUTPUT_JSON, help=f"Output JSON path (default: {DEFAULT_OUTPUT_JSON})")
    parser.add_argument("--seed", type=int, default=42, help="Random state seed")
    args = parser.parse_args()
    
    df, X, y, feature_cols, experiments, e2e_lat = load_dataset(args.dataset)
    print(f"Loaded dataset: {len(df)} samples, {len(feature_cols)} V3D hardware counter features from '{args.dataset}'.")
    
    splits, split_info = split_data(X, y, experiments, e2e_lat, random_state=args.seed)
    print(f"Train/Val/Test Split: Train={split_info['train_samples']} ({split_info['train_pct']:.1f}%), "
          f"Val={split_info['val_samples']} ({split_info['val_pct']:.1f}%), "
          f"Test={split_info['test_samples']} ({split_info['test_pct']:.1f}%)")
    
    results, trained_instances = train_and_benchmark(splits, random_state=args.seed, export_dir=args.export_dir)
    save_reports(results, split_info, feature_cols, output_csv=args.output_csv, output_json=args.output_json)


if __name__ == "__main__":
    main()

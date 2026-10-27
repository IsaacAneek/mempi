# Machine Learning & Workload Models Documentation (`MODEL.md`)

This document provides a comprehensive specification of the **workload models**, **predictive machine learning regression architectures**, **hardware counter features**, **train/validation/test split methodology**, **empirical benchmark results**, and an **end-to-end tutorial** for the MemPi GPU performance evaluation suite on Raspberry Pi 5.

---

## 1. Overview & Dual-Tier Modeling Architecture

MemPi employs a two-tier modeling framework designed to analyze, predict, and mitigate GPU performance degradation caused by concurrent CPU and memory bus contention on the Broadcom BCM2712 SoC (Raspberry Pi 5 with VideoCore VII GPU / `v3d` DRM driver):

```
+--------------------------------------------------------------------------------------------------+
|                                    MEMPI DUAL-TIER FRAMEWORK                                     |
+--------------------------------------------------------------------------------------------------+
|                                                                                                  |
|  Tier 1: GPU Micro-Benchmark Workload Tasks (EGL / OpenGL ES 3.1 Compute Shaders)                 |
|  ================================================================================                |
|  * 10 Standardized compute shader kernels executing 400 dispatches on 8,388,608 float elements   |
|  * Explicit architectural split:                                                                 |
|    - Training Tasks (6):   Sequential Memory, Reverse Memory, Poly Compute, Math Trans, Hybrid   |
|    - Validation Tasks (2): Horner Polynomial Compute, InvSqrt Hybrid                             |
|    - Test Tasks (2):       Log-Sqrt Transcendental Hybrid, Affine Arithmetic Hybrid              |
|                                                                                                  |
|                                         |                                                        |
|                                         v (Hardware Performance Profiling via DRM V3D Perfmon)   |
|                                                                                                  |
|  Tier 2: Machine Learning Predictive Regression Models                                          |
|  ================================================================================                |
|  * 93 Micro-architectural Hardware Counter Features (AXI Bus, L2T Cache, QPU, TMU, CLE/PTB)     |
|  * Target 1: Slowdown Factor (S = Latency_interference / Latency_baseline >= 1.0)                |
|  * Target 2: Absolute End-to-End Latency (ms)                                                    |
|  * 5 ML Architectures: Random Forest, Gradient Boosting, Extra Trees, Ridge Linear, SVR (RBF)    |
|                                                                                                  |
+--------------------------------------------------------------------------------------------------+
```

---

## 2. Input Features Specification

The machine learning models take as input **93 micro-architectural hardware performance counters** collected at runtime by sampling the VideoCore VII performance monitor counters through the DRM kernel interface (`/dev/dri/renderD128` via `DRM_IOCTL_V3D_PERFMON_*`).

### 2.1 Hardware Counter Categories

| Subsystem | Number of Counters | Representative Counters | Physical Significance |
| :--- | :---: | :--- | :--- |
| **AXI Memory Bus** | 18 | `AXI-write-wait-cycles`, `AXI-read-wait-cycles`, `AXI-read-trans`, `AXI-write-trans`, `AXI-reads-stalled-seen-watch-0` | Directly tracks contention, wait states, and stalls when accessing shared LPDDR4X SDRAM. |
| **L2T (L2 Texture) Cache** | 24 | `L2T-stalls-read-data`, `L2T-total-cache-miss`, `L2T-total-cache-hit`, `L2T-memory-reads`, `L2T-stalls-mem` | Measures cache hits, miss rates, memory line fills, and stalls waiting for memory read data. |
| **QPU (Quad Processing Units)** | 16 | `QPU-active`, `QPU-wait-bubble`, `QPU-stalls-TMU`, `QPU-ic-miss-bubble`, `QPU-stalls` | Instruction throughput, pipeline bubbles, instruction cache misses, and pipeline stalls. |
| **TMU (Texture Mapping Units)** | 6 | `TMU-active-cycles`, `TMU-cache-x4-stalled-cycles`, `TMU-stalled-cycles`, `TMU-total-text-quads-access` | Measures memory fetch operations, texture filtering stages, and texture cache stalls. |
| **Core & Compute Units** | 6 | `cycle-count`, `core-active`, `compute-active-cycles`, `core-memory-reads`, `core-memory-writes` | Aggregate GPU clock cycles, active execution states, and direct memory transactions. |
| **CLE / PTB / FEP / TLB** | 23 | `CLE-bin-thread-active-cycles`, `PTB-memory-reads`, `TLB-memory-reads`, `FEP-valid-quads` | Tile binning, rasterization, and frame buffer tile operations. |

### 2.2 Top 15 Feature Importances (Random Forest Gini Importance)

Hardware counter importance ranking reveals that memory-bus wait states and L2 cache read stalls are the primary contributors to GPU slowdown:

| Rank | Hardware Feature Name | Subsystem | Relative Importance | Cumulative Importance | Hardware Bottleneck Interpretation |
| :---: | :--- | :---: | :---: | :---: | :--- |
| **1** | `AXI-write-wait-cycles` | AXI Bus | **16.54%** | 16.54% | Total CPU/GPU memory bus stall time waiting on DRAM writes |
| **2** | `cycle-count` | Core | **15.83%** | 32.37% | Gross elapsed GPU clock cycles for the dispatch window |
| **3** | `core-active` | Core | **12.56%** | 44.93% | Non-idle cycles executed by the GPU processing cores |
| **4** | `L2T-stalls-read-data` | L2T Cache | **12.27%** | 57.20% | L2 Texture Cache stalls awaiting DRAM line deliveries |
| **5** | `QPU-wait-bubble` | QPU | **5.99%** | 63.19% | Pipeline stall bubbles due to pending memory references |
| **6** | `compute-active-cycles` | Compute | **5.89%** | 69.08% | Execution clock cycles dedicated to compute shader invocations |
| **7** | `AXI-reads-stalled-seen-watch-0`| AXI Bus | **4.84%** | 73.92% | Read request pipeline stalls on memory controller channel 0 |
| **8** | `TMU-cache-x4-stalled-cycles` | TMU Cache | **4.19%** | 78.11% | Texture cache cluster stalls waiting for L2 line fills |
| **9** | `AXI-read-wait-cycles` | AXI Bus | **3.87%** | 81.98% | Latency penalty during AXI read transactions |
| **10** | `QPU-stalls-TMU` | QPU / TMU | **3.81%** | 85.79% | ALU waiting on texture/buffer load results |
| **11** | `QPU-ic-miss-bubble` | QPU | **3.12%** | 88.91% | Stalls caused by instruction cache misses in QPU code |
| **12** | `TMU-stalled-cycles` | TMU | **3.10%** | 92.01% | Total stalled cycles inside the texture mapping hardware |
| **13** | `L2T-stalls-mem` | L2T Cache | **3.08%** | 95.09% | L2 cache unable to dispatch requests due to memory congestion |
| **14** | `L2T-stalls-no-wid` | L2T Cache | **2.56%** | 97.65% | Write transaction ID exhaustion on L2 buffer |
| **15** | `AXI-reads-stalled-seen-watch-1`| AXI Bus | **1.18%** | 98.83% | Read request pipeline stalls on memory controller channel 1 |

---

## 3. Train, Validation, and Test Split Methodology

To prevent data leakage and provide unbiased generalization benchmarks, the suite applies strict train/validation/test partitioning across both tiers:

### 3.1 Machine Learning Dataset Split (`dataset.csv`)

The machine learning dataset comprises **93 empirical experiment runs** covering:
- Baseline isolated runs
- Cache-resident memory stressors (`16kr`, `128kr`, `256kr`)
- Cache-evicting working sets (`1mr`, `2mr`, `4mr`)
- DRAM streaming sequential workloads (`8mr`, `64mw`, `256mr`)
- DRAM random-access stress (`8mr_rnd`, `64mw_rnd`)
- Cache coherence shared buffer contention (`32kw_t2_g`, `256kw_g`)
- CPU-side thread storms & mutex contention (`mutex1_t4`, `cpu_prime_t8`, `threads_t64`)
- Virtual memory page-fault loops (`pf_64mw_t4`, `ng_fault_t4`, `ng_mmap_t4`)

A reproducible two-stage split is performed (`random_state=42`):
1. **Initial Split:** 70% Train (65 samples) vs. 30% Holdout (28 samples).
2. **Secondary Split:** The 30% holdout is split 50/50 into Validation (14 samples) and Test (14 samples).

```
+---------------------------------------------------------------------------------+
|                              TOTAL SAMPLES: 93 (100%)                           |
+----------------------------------------------------+----------------------------+
|             TRAINING SET: 65 (69.9%)               |     HOLDOUT: 28 (30.1%)    |
| - Used for model fitting and coefficient estimation|                            |
+----------------------------------------------------+--------------+-------------+
                                                     | VALIDATION   | TEST        |
                                                     | 14 (15.1%)   | 14 (15.1%)  |
                                                     | Model tuning | Final eval  |
                                                     +--------------+-------------+
```

### 3.2 GPU Workload Tasks Architectural Split (`src/tasks/`)

The 10 GPU tasks in `build_all.py` are explicitly designed and partitioned to test different shader execution profiles:

| Split Role | Task Identifier | GLSL Kernel Implementation & Operation | Stressed Subsystem |
| :---: | :--- | :--- | :--- |
| **TRAIN** | `task1_train_mem` | 16-element sequential copy: `out_data[base+k] = in_data[base+k+1]` | Sequential L2T & DRAM Bandwidth |
| **TRAIN** | `task2_train_mem` | 8-element reverse index traversal: `idx = (MAX - 1) - base` | Prefetcher-hostile DRAM Read |
| **TRAIN** | `task3_train_comp` | Cubic polynomial: `x^3 + 3x^2 - 2x + 1` | QPU ALU Arithmetic Throughput |
| **TRAIN** | `task4_train_comp` | Transcendental math: `sin(x)*cos(x) + exp(-abs(x))` | QPU SFU (Special Function Unit) |
| **TRAIN** | `task5_train_hyb` | Dual-lane mixed: `sqrt(abs(val * 123.456)) + 1.1` | Hybrid ALU & TMU Fetch |
| **TRAIN** | `task6_train_hyb` | 4th-degree polynomial: `v^4 - 2v^2 + 0.5` | Hybrid Memory Striding & ALU |
| **VALIDATION** | `task9_val_hyb` | Fast inverse square root: `inversesqrt(abs(p) + 0.001) * 2.0` | QPU SFU Inverse Sqrt Approximation |
| **VALIDATION** | `task10_val_comp`| Horner's method polynomial: `(((0.1z + 0.2)z - 0.3)z + 0.4)z - 0.5` | QPU Fused Multiply-Add (FMA) |
| **TEST** | `task7_test_hyb1` | Cross-variable log-sqrt: `log(abs(a)+1) * sqrt(abs(b)+1)` | Unseen Transcendental Evaluation |
| **TEST** | `task8_test_hyb2` | Stride-offset linear affine transform: `x * 1.5 - 0.25` | Unseen Cache Interleave Pattern |

---

## 4. Machine Learning Model Architectures & Benchmarks

All models were evaluated on the exact same train/validation/test split. Preprocessing pipelines with `StandardScaler` are employed for distance- and gradient-sensitive models (Ridge, SVR).

### 4.1 Model 1: Random Forest Regressor (`mempi_random_forest_model.pkl`)

- **Architecture:** Bagging ensemble of 100 de-correlated decision trees. Each split optimizes Mean Squared Error (MSE) reduction over random sub-samples of features ($\sqrt{p}$).
- **Parameters:**
  ```python
  RandomForestRegressor(
      n_estimators=100,
      criterion="squared_error",
      max_depth=None,
      min_samples_split=2,
      min_samples_leaf=1,
      bootstrap=True,
      random_state=42
  )
  ```
- **Performance:**
  - **Train:** $R^2 = 0.9985$, $\text{RMSE} = 0.0901$, $\text{MAE} = 0.0354$
  - **Validation:** $R^2 = 0.9854$, $\text{RMSE} = 0.3246$, $\text{MAE} = 0.1709$
  - **Test:** $R^2 = 0.9976$, $\text{RMSE} = 0.1415$, $\text{MAE} = 0.0654$, $\text{MAPE} = 3.01\%$
  - **Fit Time:** $287.35\text{ ms}$
  - **Inference Latency:** $350.25\ \mu\text{s / sample}$

### 4.2 Model 2: Gradient Boosting Regressor (`mempi_gradient_boosting_model.pkl`)

- **Architecture:** Forward stage-wise additive modeling using gradient descent on squared-error loss:
  $$\hat{y}_m(x) = \hat{y}_{m-1}(x) + \gamma_m h_m(x)$$
  Builds sequential shallow trees (depth 3) focusing iteratively on hard-to-predict residual outliers.
- **Parameters:**
  ```python
  GradientBoostingRegressor(
      n_estimators=100,
      learning_rate=0.1,
      max_depth=3,
      loss="squared_error",
      subsample=1.0,
      random_state=42
  )
  ```
- **Performance:**
  - **Train:** $R^2 = 1.0000$, $\text{RMSE} = 0.0006$, $\text{MAE} = 0.0004$
  - **Validation:** $R^2 = 0.9995$, $\text{RMSE} = 0.0601$, $\text{MAE} = 0.0419$
  - **Test:** $R^2 = 0.9991$, $\text{RMSE} = 0.0861$, $\text{MAE} = 0.0527$, $\text{MAPE} = 1.95\%$
  - **Fit Time:** $168.22\text{ ms}$
  - **Inference Latency:** $96.13\ \mu\text{s / sample}$

### 4.3 Model 3: Extra Trees Regressor (`mempi_extra_trees_model.pkl`)

- **Architecture:** Extremely Randomized Trees ensemble. Randomizes both attribute choices and continuous cut-point thresholds to maximize variance reduction and suppress noise from transient hardware spikes.
- **Parameters:**
  ```python
  ExtraTreesRegressor(
      n_estimators=100,
      criterion="squared_error",
      max_depth=None,
      bootstrap=False,
      random_state=42
  )
  ```
- **Performance:**
  - **Train:** $R^2 = 1.0000$, $\text{RMSE} = 0.0000$, $\text{MAE} = 0.0000$
  - **Validation:** $R^2 = 0.9993$, $\text{RMSE} = 0.0697$, $\text{MAE} = 0.0349$
  - **Test:** $R^2 = 0.9990$, $\text{RMSE} = 0.0919$, $\text{MAE} = 0.0419$, $\text{MAPE} = 1.87\%$
  - **Fit Time:** $151.98\text{ ms}$
  - **Inference Latency:** $357.42\ \mu\text{s / sample}$

### 4.4 Model 4: Ridge Linear Regressor (`mempi_ridge_linear_model.pkl`)

- **Architecture:** $L_2$-penalized Tikhonov linear regression wrapped in a `StandardScaler` pipeline:
  $$\min_w \|Xw - y\|_2^2 + \alpha \|w\|_2^2$$
  Stabilizes collinear counters (e.g. `AXI-read-trans` vs `AXI-reads-seen-watch-0`).
- **Parameters:**
  ```python
  Pipeline([
      ("scaler", StandardScaler()),
      ("regressor", Ridge(alpha=1.0, solver="auto", random_state=42))
  ])
  ```
- **Performance:**
  - **Train:** $R^2 = 0.9997$, $\text{RMSE} = 0.0413$, $\text{MAE} = 0.0272$
  - **Validation:** $R^2 = 0.9993$, $\text{RMSE} = 0.0733$, $\text{MAE} = 0.0495$
  - **Test:** $R^2 = 0.9997$, $\text{RMSE} = 0.0520$, $\text{MAE} = 0.0333$, $\text{MAPE} = 1.29\%$
  - **Fit Time:** $5.44\text{ ms}$
  - **Inference Latency:** $78.66\ \mu\text{s / sample}$

### 4.5 Model 5: Support Vector Regressor (`mempi_svr_rbf_kernel_model.pkl`)

- **Architecture:** Dual $\varepsilon$-Support Vector Regression with Radial Basis Function (RBF) kernel and `StandardScaler` pipeline:
  $$K(x, x') = \exp(-\gamma \|x - x'\|^2)$$
  Constructs a margin of tolerance ($\varepsilon = 0.05$) to ignore minor counter jitter.
- **Parameters:**
  ```python
  Pipeline([
      ("scaler", StandardScaler()),
      ("regressor", SVR(kernel="rbf", C=10.0, epsilon=0.05, gamma="scale"))
  ])
  ```
- **Performance:**
  - **Train:** $R^2 = 0.9997$, $\text{RMSE} = 0.0407$, $\text{MAE} = 0.0373$
  - **Validation:** $R^2 = 0.9942$, $\text{RMSE} = 0.2038$, $\text{MAE} = 0.1363$
  - **Test:** $R^2 = 0.9976$, $\text{RMSE} = 0.1416$, $\text{MAE} = 0.1015$, $\text{MAPE} = 4.84\%$
  - **Fit Time:** $4.51\text{ ms}$
  - **Inference Latency:** $101.87\ \mu\text{s / sample}$

---

## 5. Side-by-Side Model Comparison

### 5.1 Comprehensive Benchmark Table

| Model | Architecture Family | Fit Time (ms) | Inference Latency ($\mu$s/smp) | Train $R^2$ | Val $R^2$ | Test $R^2$ | Train RMSE | Val RMSE | Test RMSE | Train MAE | Val MAE | Test MAE | Test MAPE (%) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Ridge Linear** | $L_2$ Regularized Linear | **5.44** | **78.66** | 0.9997 | 0.9993 | **0.9997** | 0.0413 | 0.0733 | **0.0520** | 0.0272 | 0.0495 | **0.0333** | **1.29%** |
| **Gradient Boosting** | Sequential Tree Boosting | 168.22 | 96.13 | 1.0000 | **0.9995** | 0.9991 | 0.0006 | **0.0601** | 0.0861 | 0.0004 | **0.0419** | 0.0527 | 1.95% |
| **Extra Trees** | Randomized Decision Forest | 151.98 | 357.42 | 1.0000 | 0.9993 | 0.9990 | **0.0000** | 0.0697 | 0.0919 | **0.0000** | 0.0349 | 0.0419 | 1.87% |
| **Random Forest** | Bagging Decision Forest | 287.35 | 350.25 | 0.9985 | 0.9854 | 0.9976 | 0.0901 | 0.3246 | 0.1415 | 0.0354 | 0.1709 | 0.0654 | 3.01% |
| **SVR (RBF Kernel)** | Kernel Support Vector | **4.51** | 101.87 | 0.9997 | 0.9942 | 0.9976 | 0.0407 | 0.2038 | 0.1416 | 0.0373 | 0.1363 | 0.1015 | 4.84% |

### 5.2 Trade-Off & Deployment Analysis

```
Inference Latency vs. Test Accuracy (MAPE)
-------------------------------------------------------------------------------------
Model                     Inference Speed                   Prediction Accuracy (MAPE)
-------------------------------------------------------------------------------------
Ridge Linear              [██████████] 78.66 us/sample      [██████████] 1.29% error
Gradient Boosting         [████████░░] 96.13 us/sample      [█████████░] 1.95% error
SVR (RBF Kernel)          [███████░░░] 101.87 us/sample     [██████░░░░] 4.84% error
Random Forest             [████░░░░░░] 350.25 us/sample     [████████░░] 3.01% error
Extra Trees               [████░░░░░░] 357.42 us/sample     [█████████░] 1.87% error
-------------------------------------------------------------------------------------
```

1. **Production Deployment Recommendation:**
   - **`Ridge Linear`** is the top-performing model overall: lowest test RMSE ($0.0520$), lowest MAPE ($1.29\%$), and fastest inference latency ($78.66\ \mu\text{s/sample}$). Its $L_2$ regularization perfectly conditions the 93 V3D counters.
   - **`Gradient Boosting`** is the recommended non-linear model: highest validation $R^2$ ($0.9995$) and sub-$100\ \mu\text{s}$ inference latency, providing reliable bounded predictions even during extreme thermal throttling.
2. **Feature Extrapolation:**
   - Tree-based models (Random Forest, Extra Trees) provide guaranteed numerical bounds within the observed slowdown range $[0.98\times, 8.04\times]$.
   - Ridge Linear provides smooth extrapolation if unobserved memory traffic pushes interference beyond $8.5\times$.

---

## 6. GPU Micro-Benchmark Workload Results (`run_benchmarks.py`)

The 10 GPU tasks were compiled via `build_all.py` with GCC (`-lEGL -lGLESv2 -lm`) and benchmarked across 400 continuous GPU dispatches:

| Benchmark Task | Split Role | Arithmetic & Memory Workload Profile | End-to-End Latency (ms) | Avg per Dispatch ($\mu$s) | Verification |
| :--- | :---: | :--- | :---: | :---: | :---: |
| `task1_train_mem` | **TRAIN** | 16-element stride sequential copy | **7608.219** | 19020.547 | **PASS** |
| `task2_train_mem` | **TRAIN** | 8-element reverse buffer read | **10301.054** | 25752.634 | **PASS** |
| `task3_train_comp` | **TRAIN** | Degree-3 cubic polynomial ALU loop | **5026.575** | 12566.438 | **PASS** |
| `task4_train_comp` | **TRAIN** | Transcendental function evaluation (`sin`, `cos`, `exp`) | **5394.569** | 13486.423 | **PASS** |
| `task5_train_hyb` | **TRAIN** | Dual-element math + square root hybrid | **3730.455** | 9326.139 | **PASS** |
| `task6_train_hyb` | **TRAIN** | 8-element stride + degree-4 polynomial | **9512.703** | 23781.757 | **PASS** |
| `task9_val_hyb` | **VALIDATION** | Fast inverse square root reciprocal hybrid | **3687.410** | 9218.526 | **PASS** |
| `task10_val_comp` | **VALIDATION** | Horner's rule 4-term polynomial evaluation | **2638.553** | 6596.384 | **PASS** |
| `task7_test_hyb1` | **TEST** | Logarithmic and square-root cross evaluation | **3685.024** | 9212.559 | **PASS** |
| `task8_test_hyb2` | **TEST** | Affine scale & shift inter-lane transform | **3739.100** | 9347.750 | **PASS** |

### Workload Observations
- **Memory-bound tasks** (`task2_train_mem` at $10.3\text{ s}$, `task6_train_hyb` at $9.5\text{ s}$, `task1_train_mem` at $7.6\text{ s}$) spend the vast majority of execution time waiting on the L2T cache and AXI memory bus.
- **Compute-bound tasks** (`task10_val_comp` at $2.6\text{ s}$, `task7_test_hyb1` at $3.7\text{ s}`) execute significantly faster due to the high arithmetic intensity of the VideoCore VII QPUs.

---

## 7. Tutorial: End-to-End Pipeline Execution Guide

This step-by-step tutorial covers the entire lifecycle: building GPU tasks, running shader benchmarks, collecting counter datasets, training ML models, and serving real-time inference.

### 7.1 Prerequisites & System Dependencies

```bash
# Update packages and install build tools, OpenGL ES headers, and stress utilities
sudo apt update
sudo apt install -y build-essential libdrm-dev sysbench libegl-dev libgles-dev stress-ng

# Install Python requirements
pip install numpy pandas scikit-learn matplotlib joblib
```

---

### 7.2 Step 1: Compiling the GPU Compute Shaders

Run `build_all.py` to generate the C sources with embedded GLSL 3.10 compute shaders in `src/tasks/` and compile them into native binaries in `bin/`:

```bash
python3 build_all.py
```

*Expected Output:*
```
Successfully compiled: task1_train_mem.c -> bin/task1_train_mem
...
Successfully compiled: task10_val_comp.c -> bin/task10_val_comp
Build process complete!
```

---

### 7.3 Step 2: Benchmarking the GPU Workloads

Execute `run_benchmarks.py` to profile end-to-end latency and dispatch overhead across all 10 GPU tasks:

```bash
python3 run_benchmarks.py
```

*Output Artifacts:*
- `benchmark_results.csv`: Structured performance metrics for each task.
- `benchmark_report.md`: Markdown summary table with verification status.

---

### 7.4 Step 3: Generating Hardware Counter Datasets

Execute system interference experiments to collect V3D counters under memory and CPU stress:

```bash
# Run representative memory and CPU interference experiments
sudo ./monitor_interference.sh -c dram_stream,cache_resident,cpu_side

# Compile the raw experiment outputs in data/*/ into dataset.csv
python3 build_dataset.py
```

*Output Artifact:*
- `dataset.csv`: 93 samples $\times$ 93 V3D hardware performance counters with calculated `slowdown` and `e2e_latency_ms`.

---

### 7.5 Step 4: Training & Benchmarking the Machine Learning Models

Run `train_models.py` to execute the full multi-model training pipeline:

```bash
python3 train_models.py --dataset dataset.csv --export-dir models --seed 42
```

*Pipeline Operations:*
1. Loads `dataset.csv` and extracts 93 V3D hardware performance counter features.
2. Performs a 70% Train, 15% Validation, 15% Test split.
3. Fits 5 distinct architectures: Random Forest, Gradient Boosting, Extra Trees, Ridge Linear, and SVR (RBF).
4. Benchmarks training time, inference latency ($\mu\text{s/sample}$), $R^2$, RMSE, MAE, and MAPE.
5. Exports models to `models/*.pkl` and generates `model_benchmark_results.csv` and `model_benchmark_results.json`.

---

### 7.6 Step 5: Real-Time Inference & Latency Prediction

Use `inference.py` to run predictions using individual models or compare all models simultaneously:

#### Option A: Predict for a Specific Interference Scenario
```bash
python3 inference.py --experiment 64mw_rnd --model models/mempi_gradient_boosting_model.pkl
```

*Output:*
```
--- Target Experiment: 64mw_rnd ---
  Ground Truth: Slowdown = 7.970x | E2E Latency = 32881.41 ms
  Model                            Pred Slowdown   Pred Latency (ms)    Error (%) 
  ------------------------------------------------------------------------
  mempi_gradient_boosting_model             7.969x         32802.04 ms      0.00%
```

#### Option B: Multi-Model Side-by-Side Comparison
```bash
python3 inference.py --compare-all
```

#### Option C: Predict on New Custom Counter Vector CSV
```bash
python3 inference.py --input-csv custom_sample.csv --model models/mempi_ridge_linear_model.pkl
```

---

### 7.7 Step 6: Visualizing Interference & Parameters

Run `analysis/mem-gpu.py` with multi-model evaluation enabled:

```bash
python3 analysis/mem-gpu.py --evaluate-models
```

*Generated Visualizations (saved to `analysis/plots/`):*
1. `mem_gpu_absolute_latency.png`: Dual-panel showing E2E/Compute vs E2E-GPU Residual.
2. `mem_gpu_degradation_comparison.png`: Grouped degradation factor comparison across all scenarios.
3. `mem_gpu_residual_vs_compute.png`: Compute latency vs E2E-GPU residual and overhead ratio.
4. `mem_gpu_blocksize_vs_latencies.png`: Working-set progression through L1, L2, L3, and DRAM.
5. `mem_gpu_bandwidth_vs_latency.png`: Sysbench bandwidth vs GPU latency.
6. `mem_gpu_throughput_timeseries.png`: Stress throughput time-series during GPU execution.


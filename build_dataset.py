import os
import csv

DATA_DIR = "data"

def parse_gpu_task(file_path):
    metrics = {}
    if not os.path.exists(file_path): return metrics
    with open(file_path, "r") as fh:
        for line in fh:
            if "End-to-end latency:" in line:
                metrics["e2e_latency_ms"] = float(line.split(":")[1].strip().replace(" ms", ""))
    return metrics

def parse_v3d_counters(file_path):
    counter_sums = {}
    if not os.path.exists(file_path): return counter_sums
    with open(file_path, "r") as fh:
        for line in fh:
            if line.startswith("#") or not line.strip(): continue
            parts = line.split()
            if len(parts) >= 7:
                try:
                    counter_sums[parts[5]] = counter_sums.get(parts[5], 0.0) + float(parts[6])
                except ValueError: pass
    return counter_sums

def main():
    base_metrics = parse_gpu_task(os.path.join(DATA_DIR, "baseline", "gpu_task.txt"))
    base_time = base_metrics.get("e2e_latency_ms")
    if not base_time: print("Baseline missing!"); return
    
    raw_data = []
    all_counters = set()
    for exp in os.listdir(DATA_DIR):
        exp_dir = os.path.join(DATA_DIR, exp)
        if not os.path.isdir(exp_dir) or exp == "baseline": continue
        g_metrics = parse_gpu_task(os.path.join(exp_dir, "gpu_task.txt"))
        if "e2e_latency_ms" not in g_metrics: continue
        counters = parse_v3d_counters(os.path.join(exp_dir, "v3d_counters.txt"))
        for k in counters.keys(): all_counters.add(k)
        raw_data.append({"experiment": exp, "e2e_latency_ms": g_metrics["e2e_latency_ms"], "slowdown": g_metrics["e2e_latency_ms"] / base_time, "counters": counters})
    
    fieldnames = ["experiment", "e2e_latency_ms", "slowdown"] + sorted(list(all_counters))
    with open("dataset.csv", "w", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for item in raw_data:
            row = {"experiment": item["experiment"], "e2e_latency_ms": item["e2e_latency_ms"], "slowdown": item["slowdown"]}
            row.update(item["counters"])
            writer.writerow(row)
    print(f"Done! Created dataset.csv with {len(raw_data)} samples and {len(fieldnames)} features.")

if __name__ == "__main__": main()

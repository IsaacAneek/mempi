import os
import subprocess
import re
import csv
from datetime import datetime

bin_dir = "bin"
executables = sorted([f for f in os.listdir(bin_dir) if os.path.isfile(os.path.join(bin_dir, f))])

results = []
print("Running benchmarks across all tasks...\n")

for exe in executables:
    exe_path = os.path.join(bin_dir, exe)
    if not os.access(exe_path, os.X_OK):
        continue
        
    print(f"Profiling {exe}...")
    res = subprocess.run([exe_path], capture_output=True, text=True)
    
    if res.returncode != 0:
        print(f"Error running {exe}:\n{res.stderr}")
        continue
        
    output = res.stdout
    
    # Parse metrics from stdout
    lat_match = re.search(r"End-to-end latency:\s+([\d.]+)\s+ms", output)
    avg_match = re.search(r"Average per dispatch:\s+([\d.]+)\s+us", output)
    ver_match = re.search(r"Verification:\s+(\w+)", output)
    
    e2e_ms = float(lat_match.group(1)) if lat_match else 0.0
    avg_us = float(avg_match.group(1)) if avg_match else 0.0
    status = ver_match.group(1) if ver_match else "UNKNOWN"
    
    results.append({
        "Task": exe,
        "E2E Latency (ms)": e2e_ms,
        "Avg Dispatch (us)": avg_us,
        "Status": status
    })

# Save to CSV
csv_file = "benchmark_results.csv"
with open(csv_file, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=["Task", "E2E Latency (ms)", "Avg Dispatch (us)", "Status"])
    writer.writeheader()
    writer.writerows(results)

# Generate Markdown Report
md_file = "benchmark_report.md"
with open(md_file, "w", encoding="utf-8") as f:
    f.write(f"# GPU Compute Shader Benchmark Report\n")
    f.write(f"**Execution Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
    f.write("| Task | E2E Latency (ms) | Avg Dispatch (us) | Status |\n")
    f.write("| :--- | :---: | :---: | :---: |\n")
    for r in results:
        f.write(f"| `{r['Task']}` | {r['E2E Latency (ms)']:.3f} | {r['Avg Dispatch (us)']:.3f} | **{r['Status']}** |\n")

print(f"\nBenchmarks complete! Results saved to {csv_file} and {md_file}.")

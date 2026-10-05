# Generates: timing_data/timing_report_full_<timestamp>.html
# Shows complete capture latency history (all data points, downsampled for clarity)

import csv
import os
import json
import datetime
from collections import defaultdict

LOG_FILE   = "/home/khojahlab/SpringXYZ/logs/actions.csv"
TIMING_DIR = "/home/khojahlab/SpringXYZ/timing_data"
os.makedirs(TIMING_DIR, exist_ok=True)
timestamp  = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
OUTPUT     = os.path.join(TIMING_DIR, f"timing_report_full_{timestamp}.html")

rows_by_action = defaultdict(list)
timeline       = []

with open(LOG_FILE, 'r') as f:
    for row in csv.DictReader(f):
        timeline.append(row)
        if row['latency_us']:
            rows_by_action[row['action']].append(int(row['latency_us']))

all_capture_labels  = []
all_capture_values  = []
all_capture_actions = []

all_scan_labels  = []
all_scan_values  = []
all_scan_actions = []

for row in timeline:
    if row['latency_us']:
        ts  = row['timestamp']
        val = round(int(row['latency_us']) / 1000, 2)
        act = row['action']
        if act.startswith('CAPTURE_'):
            all_capture_labels.append(ts)
            all_capture_values.append(val)
            all_capture_actions.append(act)
        else:
            all_scan_labels.append(ts)
            all_scan_values.append(val)
            all_scan_actions.append(act)

generated_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
n_captures   = len(all_capture_labels)
n_scans      = len(all_scan_labels)

capture_json = json.dumps({
    "labels":  all_capture_labels,
    "values":  all_capture_values,
    "actions": all_capture_actions,
})
scan_json = json.dumps({
    "labels":  all_scan_labels,
    "values":  all_scan_values,
    "actions": all_scan_actions,
})

print(f"Total capture events: {n_captures}")
print(f"Total scan events:    {n_scans}")
print(f"Report saved to:      {OUTPUT}\n")

html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Microscopy Telemetry — Full History Report</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: 'Times New Roman', Times, serif;
    background: #ffffff;
    color: #1a1a1a;
    padding: 48px 56px;
    max-width: 1200px;
    margin: 0 auto;
  }}
  .report-header {{
    border-top: 3px solid #1a1a1a;
    border-bottom: 1px solid #1a1a1a;
    padding: 18px 0 14px;
    margin-bottom: 32px;
  }}
  .report-header h1 {{
    font-size: 22px;
    font-weight: bold;
    letter-spacing: 1px;
    text-transform: uppercase;
    margin-bottom: 4px;
  }}
  .report-header .meta {{
    font-size: 12px;
    color: #555;
    font-style: italic;
  }}
  .report-header .meta span {{ margin-right: 24px; }}
  .section-title {{
    font-size: 13px;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 2px;
    color: #1a1a1a;
    border-bottom: 1px solid #aaa;
    padding-bottom: 5px;
    margin-bottom: 6px;
  }}
  .section-note {{
    font-size: 11px;
    color: #666;
    font-style: italic;
    margin-bottom: 14px;
  }}
  .card {{ margin-bottom: 48px; }}
  canvas {{ width: 100% !important; }}
  .save-btn {{
    margin-top: 8px;
    font-family: 'Times New Roman', Times, serif;
    font-size: 11px;
    padding: 4px 12px;
    border: 1px solid #aaa;
    background: #f5f5f5;
    cursor: pointer;
  }}
  .save-btn:hover {{ background: #e8e8e8; }}
  .report-footer {{
    border-top: 1px solid #aaa;
    padding-top: 14px;
    margin-top: 8px;
    font-size: 11px;
    color: #444;
    line-height: 2;
  }}
  .report-footer b {{ color: #1a1a1a; }}
  code {{
    font-family: 'Courier New', monospace;
    background: #f0f0f0;
    padding: 1px 4px;
    border: 1px solid #ccc;
    font-size: 10px;
  }}
</style>
</head>
<body>

<div class="report-header">
  <h1>Microscopy Platform — Full Capture Latency History</h1>
  <div class="meta">
    <span>Institution: UC San Diego &mdash; Reem Khojah Research Lab</span>
    <span>Device: SpringXYZ Imaging System</span><br>
    <span>Generated: {generated_at}</span>
    <span>Source: {LOG_FILE}</span>
  </div>
</div>

<!-- Figure 1: Full capture latency history -->
<div class="card">
  <div class="section-title">Figure 1 &mdash; Capture Latency — Complete History (ms)</div>
  <div class="section-note">
    All {n_captures} capture events across the full observation period.
    Points are downsampled for visual clarity (every 3rd event plotted).
    Hover to inspect individual values. X-axis shows timestamp (HH:MM:SS).
  </div>
  <canvas id="fullCaptureChart" height="120"></canvas>
  <button class="save-btn" onclick="saveChart('fullCaptureChart', 'Figure1_CaptureLatency_FullHistory')">Save Figure</button>
</div>

<!-- Figure 2: Full scan latency history -->
<div class="card">
  <div class="section-title">Figure 2 &mdash; Full Scan Duration — Complete History (ms)</div>
  <div class="section-note">
    All {n_scans} complete scan events across the full observation period.
    Each point represents one complete 6-chamber automated scan.
    Hover to inspect individual values.
  </div>
  <canvas id="fullScanChart" height="120"></canvas>
  <button class="save-btn" onclick="saveChart('fullScanChart', 'Figure2_ScanDuration_FullHistory')">Save Figure</button>
</div>

<div class="report-footer">
  <b>Notes:</b><br>
  Latency measurements recorded via <code>time.perf_counter()</code> on Raspberry Pi (Linux).
  All values converted from microseconds to milliseconds.<br>
  Capture trend includes all six chamber capture actions combined.
  For per-chamber breakdown, refer to the standard timing report (<code>timing_summary.py</code>).<br>
  Downsampling (N=3) is applied to the capture trend for rendering performance; no data is discarded from the CSV.
</div>

<script>
Chart.defaults.devicePixelRatio = 4;

const captureData = {capture_json};
const scanData    = {scan_json};

const GRID_COLOR  = '#cccccc';
const TICK_COLOR  = '#444444';
const LABEL_COLOR = '#222222';
const FONT        = {{'family': "'Times New Roman', Times, serif", 'size': 11}};

function sharedScales(yLabel) {{
  return {{
    x: {{
      ticks: {{
        color: TICK_COLOR,
        font: {{ ...FONT, size: 9 }},
        maxTicksLimit: 12,
        autoSkip: true,
        maxRotation: 45,
        minRotation: 45,
      }},
      grid:   {{ color: GRID_COLOR, lineWidth: 1 }},
      border: {{ color: '#888' }},
    }},
    y: {{
      ticks: {{ color: TICK_COLOR, font: FONT }},
      grid:   {{ color: GRID_COLOR, lineWidth: 1 }},
      border: {{ color: '#888' }},
      title:  {{ display: true, text: yLabel, color: LABEL_COLOR, font: FONT }}
    }}
  }};
}}

function downsample(arr, n) {{
  return arr.filter((_, i) => i % n === 0);
}}

const N = 3;
const capLabels  = downsample(captureData.labels,  N);
const capValues  = downsample(captureData.values,  N);
const capActions = downsample(captureData.actions, N);

new Chart(document.getElementById('fullCaptureChart'), {{
  type: 'line',
  data: {{
    labels: capLabels,
    datasets: [{{
      data:            capValues,
      borderColor:     '#2c5f8acc',
      backgroundColor: '#2c5f8a18',
      borderWidth:     0.8,
      pointRadius:     0,
      tension:         0.1,
      fill:            false,
    }}]
  }},
  options: {{
    responsive: true,
    animation: false,
    plugins: {{
      legend: {{ display: false }},
      tooltip: {{
        callbacks: {{
          title: (items) => capActions[items[0].dataIndex] + '  ' + capLabels[items[0].dataIndex],
          label: (item)  => item.formattedValue + ' ms'
        }}
      }}
    }},
    scales: sharedScales('Duration (ms)')
  }}
}});

new Chart(document.getElementById('fullScanChart'), {{
  type: 'line',
  data: {{
    labels: scanData.labels,
    datasets: [{{
      data:            scanData.values,
      borderColor:     '#7a2c2ccc',
      backgroundColor: '#7a2c2c18',
      borderWidth:     1,
      pointRadius:     1,
      pointBackgroundColor: '#7a2c2c',
      tension:         0.1,
      fill:            false,
    }}]
  }},
  options: {{
    responsive: true,
    animation: false,
    plugins: {{
      legend: {{ display: false }},
      tooltip: {{
        callbacks: {{
          title: (items) => scanData.actions[items[0].dataIndex] + '  ' + scanData.labels[items[0].dataIndex],
          label: (item)  => item.formattedValue + ' ms'
        }}
      }}
    }},
    scales: sharedScales('Duration (ms)')
  }}
}});

function saveChart(canvasId, filename) {{
  var link = document.createElement('a');
  link.download = filename + '.png';
  link.href = document.getElementById(canvasId).toDataURL('image/png', 1.0);
  link.click();
}}
</script>
</body>
</html>"""

with open(OUTPUT, 'w') as f:
    f.write(html)

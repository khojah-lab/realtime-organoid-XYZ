# File: timing_data/timing_report_<timestamp>.html

import csv
import os
import json
import datetime
from collections import defaultdict

LOG_FILE   = "/home/khojahlab/SpringXYZ/logs/actions.csv"
TIMING_DIR = "/home/khojahlab/SpringXYZ/timing_data"
os.makedirs(TIMING_DIR, exist_ok=True)
timestamp  = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
OUTPUT     = os.path.join(TIMING_DIR, f"timing_report_{timestamp}.html")

rows_by_action = defaultdict(list)
timeline       = []

with open(LOG_FILE, 'r') as f:
    for row in csv.DictReader(f):
        timeline.append(row)
        if row['latency_us']:
            rows_by_action[row['action']].append(int(row['latency_us']))

def percentile(data, p):
    s   = sorted(data)
    idx = int(len(s) * p / 100)
    return s[min(idx, len(s) - 1)]

stats = {}
for action, times in sorted(rows_by_action.items()):
    n      = len(times)
    mean   = sum(times) / n
    median = percentile(times, 50)
    p95    = percentile(times, 95)
    mn     = min(times)
    mx     = max(times)
    std    = (sum((t - mean) ** 2 for t in times) / n) ** 0.5
    stats[action] = {
        "count":  n,
        "mean":   round(mean   / 1000, 2),
        "median": round(median / 1000, 2),
        "std":    round(std    / 1000, 2),
        "p95":    round(p95    / 1000, 2),
        "min":    round(mn     / 1000, 2),
        "max":    round(mx     / 1000, 2),
        "raw_ms": [round(t / 1000, 2) for t in times],
    }

trend_labels  = []
trend_values  = []
trend_actions = []
for row in timeline:
    if row['latency_us']:
        trend_labels.append(row['timestamp'][-8:])
        trend_values.append(round(int(row['latency_us']) / 1000, 2))
        trend_actions.append(row['action'])

trend_labels  = trend_labels[-200:]
trend_values  = trend_values[-200:]
trend_actions = trend_actions[-200:]

def make_histogram(values_ms, n_bins=20):
    if not values_ms:
        return [], []
    mn    = min(values_ms)
    mx    = max(values_ms)
    if mn == mx:
        return [str(mn)], [len(values_ms)]
    width  = (mx - mn) / n_bins
    bins   = [mn + i * width for i in range(n_bins)]
    counts = [0] * n_bins
    for v in values_ms:
        idx = min(int((v - mn) / width), n_bins - 1)
        counts[idx] += 1
    return [f"{b:.0f}" for b in bins], counts

scan_raw = stats.get("FULL_SCAN", {}).get("raw_ms", [])
hist_labels, hist_counts = make_histogram(scan_raw, n_bins=20)

print(f"\n{'ACTION':<25} {'N':>4} {'AVG ms':>10} {'MED ms':>10} "
      f"{'STD ms':>8} {'P95 ms':>10} {'MIN ms':>10} {'MAX ms':>10}")
print("─" * 95)
for action, s in stats.items():
    print(f"{action:<25} {s['count']:>4} {s['mean']:>10} {s['median']:>10} "
          f"{s['std']:>8} {s['p95']:>10} {s['min']:>10} {s['max']:>10}")
print(f"\nReport saved to: {OUTPUT}\n")

table_rows = ""
for action, s in stats.items():
    table_rows += f"""
        <tr>
            <td>{action}</td>
            <td>{s['count']}</td>
            <td>{s['mean']}</td>
            <td>{s['median']}</td>
            <td>{s['std']}</td>
            <td>{s['p95']}</td>
            <td>{s['min']}</td>
            <td>{s['max']}</td>
        </tr>"""

stats_json   = json.dumps(stats)
trend_json   = json.dumps({
    "labels":  trend_labels,
    "values":  trend_values,
    "actions": trend_actions,
})
hist_json    = json.dumps({
    "labels": hist_labels,
    "counts": hist_counts,
})
generated_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Microscopy Telemetry Report</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
  /* ── Reset + Base ── */
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: 'Times New Roman', Times, serif;
    background: #ffffff;
    color: #1a1a1a;
    padding: 48px 56px;
    max-width: 1200px;
    margin: 0 auto;
  }}

  /* ── Header ── */
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
  .report-header .meta span {{
    margin-right: 24px;
  }}

  /* ── Section headings ── */
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

  /* ── Grid ── */
  .grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 40px 48px;
    margin-bottom: 40px;
  }}
  .card {{ }}
  .card.full {{ grid-column: 1 / -1; }}
  canvas {{ width: 100% !important; }}

  /* ── Table ── */
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
    font-family: 'Times New Roman', Times, serif;
  }}
  thead tr {{
    border-top: 2px solid #1a1a1a;
    border-bottom: 1px solid #1a1a1a;
  }}
  th {{
    text-align: left;
    padding: 7px 10px;
    font-size: 11px;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: #1a1a1a;
    background: #f5f5f5;
  }}
  td {{
    padding: 6px 10px;
    border-bottom: 1px solid #ddd;
    color: #1a1a1a;
  }}
  tbody tr:last-child td {{
    border-bottom: 2px solid #1a1a1a;
  }}
  tbody tr:hover td {{ background: #f9f9f9; }}
  td:first-child {{ font-style: italic; }}

  /* ── Footer notes ── */
  .report-footer {{
    border-top: 1px solid #aaa;
    padding-top: 14px;
    margin-top: 8px;
    font-size: 11px;
    color: #444;
    line-height: 2;
  }}
  .report-footer b {{ font-weight: bold; color: #1a1a1a; }}
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

<!-- ── Report Header ── -->
<div class="report-header">
  <h1>Microscopy Platform — Telemetry Performance Report</h1>
  <div class="meta">
    <span>Institution: UC San Diego &mdash; Reem Khojah Research Lab</span>
    <span>Device: SpringXYZ Imaging System</span><br>
    <span>Generated: {generated_at}</span>
    <span>Source: {LOG_FILE}</span>
  </div>
</div>

<div class="grid">

  <!-- Fig 1: Camera capture bar -->
  <div class="card">
    <div class="section-title">Figure 1 &mdash; Camera Capture Latency by Chamber (ms)</div>
    <div class="section-note">Mean capture duration per chamber. Scale limited to capture range (~10&ndash;50 ms).</div>
    <canvas id="captureChart"></canvas>
  </div>

  <!-- Fig 2: Scan + motion bar -->
  <div class="card">
    <div class="section-title">Figure 2 &mdash; Full Scan &amp; Motion Latency (ms)</div>
    <div class="section-note">Mean duration for complete scans and motor movements. Independent scale from Figure 1.</div>
    <canvas id="scanChart"></canvas>
  </div>

  <!-- Fig 3: Histogram -->
  <div class="card full">
    <div class="section-title">Figure 3 &mdash; Full Scan Duration Distribution (ms)</div>
    <div class="section-note">
      Frequency histogram of complete scan durations across all recorded trials (n = {len(scan_raw)}).
      A unimodal distribution indicates consistent timing. Two distinct peaks indicate bimodal behaviour,
      suggesting two operating modes. See footer for diagnostic guidance.
    </div>
    <canvas id="histChart"></canvas>
  </div>

  <!-- Fig 4: Event count -->
  <div class="card">
    <div class="section-title">Figure 4 &mdash; Event Frequency by Action</div>
    <div class="section-note">Total logged occurrences per action type across the full observation period.</div>
    <canvas id="countChart"></canvas>
  </div>

  <!-- Fig 5: Capture trend -->
  <div class="card">
    <div class="section-title">Figure 5 &mdash; Capture Latency Over Time (ms)</div>
    <div class="section-note">Last 200 capture events in chronological order. Upward drift may indicate mechanical wear.</div>
    <canvas id="trendCaptureChart"></canvas>
  </div>

  <!-- Fig 6: Scan trend -->
  <div class="card full">
    <div class="section-title">Figure 6 &mdash; Full Scan Duration Over Time (ms)</div>
    <div class="section-note">Each data point represents one complete 6-chamber scan. Step changes between two levels confirm bimodal behaviour.</div>
    <canvas id="trendScanChart"></canvas>
  </div>

  <!-- Table 1: Stats -->
  <div class="card full">
    <div class="section-title">Table 1 &mdash; Descriptive Statistics Summary</div>
    <div class="section-note">All latency values in milliseconds. Std Dev column highlighted for consistency assessment.</div>
    <table>
      <thead>
        <tr>
          <th>Action</th>
          <th>n</th>
          <th>Mean (ms)</th>
          <th>Median (ms)</th>
          <th>Std Dev (ms)</th>
          <th>95th Pct (ms)</th>
          <th>Min (ms)</th>
          <th>Max (ms)</th>
        </tr>
      </thead>
      <tbody>{table_rows}</tbody>
    </table>
  </div>

</div>

<!-- ── Footer ── -->
<div class="report-footer">
  <b>Notes &amp; Methodology</b><br>
  Latency measurements recorded via <code>time.perf_counter()</code> on Raspberry Pi (Linux).
  All values converted from microseconds to milliseconds for display.
  The 95th percentile (P95) represents the worst-case realistic latency: 95% of events complete faster than this value.
  Standard deviation reflects timing consistency; elevated values warrant mechanical inspection.
  Median is reported alongside mean as a more robust central tendency estimate in the presence of outliers.<br>
  <b>Bimodal Diagnostic:</b> If Figure 3 shows two distinct peaks, run <code>vcgencmd get_throttled</code> on the Pi to check
  for thermal throttling. A return value of <code>0x0</code> rules out throttling; investigate positional motor friction instead.
</div>

<script>
const stats = {stats_json};
const trend = {trend_json};
const hist  = {hist_json};

// Neutral palette suitable for print / light mode
const BAR_COLORS = [
  '#2c5f8a','#3a7abf','#4e9dd4','#6db8e8',
  '#1a3f5c','#255273','#82b8d4','#afd0e5'
];

const GRID_COLOR  = '#cccccc';
const TICK_COLOR  = '#444444';
const LABEL_COLOR = '#222222';
const FONT        = {{'family': "'Times New Roman', Times, serif", 'size': 11}};

const allActions     = Object.keys(stats);
const captureActions = allActions.filter(a =>  a.startsWith('CAPTURE_'));
const otherActions   = allActions.filter(a => !a.startsWith('CAPTURE_'));

function sharedScales(yLabel) {{
  return {{
    x: {{
      ticks: {{ color: TICK_COLOR, font: FONT }},
      grid:  {{ color: GRID_COLOR, lineWidth: 1 }},
      border: {{ color: '#888' }},
    }},
    y: {{
      ticks: {{ color: TICK_COLOR, font: FONT }},
      grid:  {{ color: GRID_COLOR, lineWidth: 1 }},
      border: {{ color: '#888' }},
      title: {{ display: true, text: yLabel, color: LABEL_COLOR, font: FONT }}
    }}
  }};
}}

function makeBarChart(id, actions) {{
  new Chart(document.getElementById(id), {{
    type: 'bar',
    data: {{
      labels: actions,
      datasets: [{{
        data:            actions.map(a => stats[a].mean),
        backgroundColor: actions.map((_, i) => BAR_COLORS[i % BAR_COLORS.length] + 'bb'),
        borderColor:     actions.map((_, i) => BAR_COLORS[i % BAR_COLORS.length]),
        borderWidth: 1,
      }}]
    }},
    options: {{
      responsive: true,
      plugins: {{ legend: {{ display: false }} }},
      scales: sharedScales('Duration (ms)')
    }}
  }});
}}

makeBarChart('captureChart', captureActions);
makeBarChart('scanChart',    otherActions);

new Chart(document.getElementById('histChart'), {{
  type: 'bar',
  data: {{
    labels: hist.labels,
    datasets: [{{
      label: 'Scan count',
      data:  hist.counts,
      backgroundColor: '#2c5f8abb',
      borderColor:     '#2c5f8a',
      borderWidth: 1,
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{
      legend: {{ display: false }},
      tooltip: {{
        callbacks: {{
          title: (items) => items[0].label + ' ms',
          label: (item)  => item.formattedValue + ' scans in this bin'
        }}
      }}
    }},
    scales: {{
      x: {{
        ticks: {{ color: TICK_COLOR, font: {{ ...FONT, size: 9 }}, maxTicksLimit: 15 }},
        grid:  {{ color: GRID_COLOR, lineWidth: 1 }},
        border: {{ color: '#888' }},
        title: {{ display: true, text: 'Scan duration (ms)', color: LABEL_COLOR, font: FONT }}
      }},
      y: {{
        ticks: {{ color: TICK_COLOR, font: FONT, stepSize: 1 }},
        grid:  {{ color: GRID_COLOR, lineWidth: 1 }},
        border: {{ color: '#888' }},
        title: {{ display: true, text: 'Number of scans', color: LABEL_COLOR, font: FONT }}
      }}
    }}
  }}
}});

new Chart(document.getElementById('countChart'), {{
  type: 'bar',
  data: {{
    labels: allActions,
    datasets: [{{
      data:            allActions.map(a => stats[a].count),
      backgroundColor: '#3a7abfbb',
      borderColor:     '#3a7abf',
      borderWidth: 1,
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: sharedScales('Number of events')
  }}
}});

function makeTrendChart(id, filterFn, color) {{
  const labels  = [];
  const values  = [];
  const actions = [];
  trend.labels.forEach((l, i) => {{
    if (filterFn(trend.actions[i])) {{
      labels.push(l);
      values.push(trend.values[i]);
      actions.push(trend.actions[i]);
    }}
  }});
  new Chart(document.getElementById(id), {{
    type: 'line',
    data: {{
      labels,
      datasets: [{{
        data: values,
        borderColor:     color,
        backgroundColor: color + '22',
        borderWidth: 1.5,
        pointRadius: 1.0,
        pointBackgroundColor: color,
        tension: 0.15,
        fill: false,
      }}]
    }},
    options: {{
      responsive: true,
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{
          callbacks: {{
            title: (items) => actions[items[0].dataIndex],
            label: (item)  => item.formattedValue + ' ms'
          }}
        }}
      }},
      scales: {{
        x: {{
          ticks: {{ color: TICK_COLOR, font: {{ ...FONT, size: 9 }}, maxTicksLimit: 20 }},
          grid:  {{ color: GRID_COLOR, lineWidth: 1 }},
          border: {{ color: '#888' }},
        }},
        y: {{
          ticks: {{ color: TICK_COLOR, font: FONT }},
          grid:  {{ color: GRID_COLOR, lineWidth: 1 }},
          border: {{ color: '#888' }},
          title: {{ display: true, text: 'Duration (ms)', color: LABEL_COLOR, font: FONT }}
        }}
      }}
    }}
  }});
}}

makeTrendChart('trendCaptureChart', a =>  a.startsWith('CAPTURE_'), '#2c5f8a');
makeTrendChart('trendScanChart',    a => !a.startsWith('CAPTURE_'), '#7a2c2c');

// Save figure buttons
document.querySelectorAll('canvas').forEach(function(canvas) {{
    var btn = document.createElement('button');
    btn.textContent = 'Save Figure';
    btn.style = 'margin-top:8px; font-family:Times New Roman,serif; font-size:11px; padding:4px 12px; border:1px solid #aaa; background:#f5f5f5; cursor:pointer;';
    btn.onclick = function() {{
        var link = document.createElement('a');
        link.download = canvas.id + '.png';
        link.href = canvas.toDataURL('image/png', 1.0);
        link.click();
    }};
    canvas.parentNode.appendChild(btn);
}});
</script>
</script>
</body>
</html>"""

with open(OUTPUT, 'w') as f:
    f.write(html)

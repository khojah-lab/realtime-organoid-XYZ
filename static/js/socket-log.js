// =========================
// SOCKET.IO, LIVE ACTION LOG & HARDWARE WATCHDOG
// =========================
const socket = io('/');
window.socket = socket;

// Action log formatting & severity classes
function formatLogLatency(us) {
    if (!us || us <= 0) return '';
    if (us >= 1000000) return ' [' + (us / 1000000).toFixed(2) + ' s]';
    if (us >= 10000)   return ' [' + Math.round(us / 1000) + ' ms]';
    return ' [' + us + ' us]';
}

function classifyLogClass(action) {
    var a = (action || '').toUpperCase();
    if (a.indexOf('REJECT') !== -1 || a.indexOf('ERROR') !== -1 || a.indexOf('UNCERTAIN') !== -1) {
        return 'log-error';
    }
    if (a.indexOf('CLAMP') !== -1 || a.indexOf('SYNC') !== -1 || a.indexOf('DRIFT') !== -1) {
        return 'log-warn';
    }
    if (a.indexOf('SCAN_') !== -1 || a.indexOf('CAPTURE_') !== -1) {
        return 'log-scan';
    }
    return 'log-ok';
}

function appendLogRow(data, prepend) {
    var log = document.getElementById('action-log');
    if (!log) return;
    var row = document.createElement('div');
    row.className = 'log-row ' + classifyLogClass(data.action);
    var timeShort = (data.timestamp || '').split(' ').pop() || data.timestamp;
    var lat = formatLogLatency(data.latency_us);
    row.textContent = '[' + timeShort + ']  ' + data.action + lat;
    row.title = data.timestamp || '';

    if (prepend !== false) {
        log.prepend(row);
    } else {
        log.appendChild(row);
    }

    // Cap at 120 rows so the DOM doesn't grow forever
    while (log.children.length > 120) {
        log.removeChild(log.lastChild);
    }
}

socket.on('new_action', function(data) {
    appendLogRow(data, true);
});

$("#btn-clear-log").click(function() {
    $("#action-log").empty();
});

// Hardware connectivity banner & camera stream watchdog
function updateHardwareBanner(disconnected) {
    var banner = document.getElementById('hardware-error-banner');
    if (!banner) return;
    if (disconnected && disconnected.length > 0) {
        banner.textContent = '\u26a0 Disconnected Hardware: ' + disconnected.join('  |  ');
        banner.style.display = 'block';
    } else {
        banner.style.display = 'none';
    }
}

var _cameraWasStalled = false;
var _lastStreamReconnectMs = 0;

function reconnectVideoStream() {
    var now = Date.now();
    if (now - _lastStreamReconnectMs < 3000) return;
    _lastStreamReconnectMs = now;
    var img = document.getElementById('camera_feed');
    if (img) {
        img.src = '/video?t=' + now;
    }
}

function updateCameraWatchdog(camera) {
    if (!camera) return;
    var statusEl = document.getElementById('stream_status');
    var img = document.getElementById('camera_feed');

    if (!camera.connected) {
        if (statusEl) statusEl.textContent = '\u26a0 Camera not connected.';
        _cameraWasStalled = true;
        return;
    }

    if (!camera.streaming) {
        if (statusEl) statusEl.textContent = '\u26a0 Camera stream stalled \u2014 auto-recovering...';
        _cameraWasStalled = true;
        return;
    }

    if (statusEl) statusEl.textContent = '';
    if (_cameraWasStalled || (img && img.complete && img.naturalWidth === 0)) {
        _cameraWasStalled = false;
        reconnectVideoStream();
    }
}

function markCameraStreamStalled(msg) {
    _cameraWasStalled = true;
    var statusEl = document.getElementById('stream_status');
    if (statusEl && msg) {
        statusEl.textContent = msg;
    }
}

$("#camera_feed").on("error", function() {
    _cameraWasStalled = true;
    document.getElementById('stream_status').textContent = '\u26a0 Stream unavailable.';
});

$("#camera_feed").on("load", function() {
    if (!_cameraWasStalled) {
        document.getElementById('stream_status').textContent = '';
    }
});

socket.on('hardware_status', function(msg) {
    updateHardwareBanner(msg.disconnected);
    if (msg.camera) updateCameraWatchdog(msg.camera);
});

socket.on('connect', function() {
    if (_cameraWasStalled) {
        reconnectVideoStream();
    }
});

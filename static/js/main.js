// =========================
// PAGE LOAD HYDRATION & POLLING
// =========================
window.addEventListener('load', function() {
    $.getJSON({ type: "GET", url: '/get_system_parameters_from_html' });
    $.getJSON('/nav/state', function(state) { updateNavUI(state); });
    $.getJSON('/recent_logs', function(res) {
        if (res && res.logs) {
            $("#action-log").empty();
            res.logs.forEach(function(item) { appendLogRow(item, false); });
        }
    });
    $.getJSON('/scan_status', function(data) { setScanRunning(!!data.running); });
    $.getJSON('/hardware_status', function(data) {
        updateHardwareBanner(data.disconnected);
        updateCameraWatchdog(data.camera);
    });

    // Poll hardware & camera watchdog every 5s to detect stalled feeds and auto-reconnect
    setInterval(function() {
        $.getJSON('/hardware_status', function(data) {
            updateHardwareBanner(data.disconnected);
            updateCameraWatchdog(data.camera);
        }).fail(function() {
            markCameraStreamStalled('\u26a0 Server connection lost \u2014 reconnecting...');
        });
    }, 5000);

    // Poll scan status every 30s in case socket misses an update
    setInterval(function() {
        $.getJSON('/scan_status', function(data) {
            $("#scan_last").text(data.last_scan || "Never");
            $("#scan_next").text(data.next_scan || "—");
            $("#scan_progress").text(data.current_step || "");
            if (data.next_scan && data.next_scan !== "Calculating..." && data.next_scan !== "—") {
                updateCountdown(data.next_scan);
            }
        });
    }, 30000);
});

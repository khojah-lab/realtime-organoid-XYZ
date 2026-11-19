// =========================
// SCANNER CONTROLS, LANDMARK VERIFY & ORGANOID DETECTION
// =========================

// Countdown timer for next scan
function updateCountdown(nextScanStr) {
    if (window.countdownInterval) {
        clearInterval(window.countdownInterval);
    }
    window.countdownInterval = setInterval(function() {
        var now = new Date();
        var nextScan = new Date(nextScanStr);
        var diff = nextScan - now;
        if (diff <= 0) {
            $("#scan_countdown").text("Starting scan...");
            clearInterval(window.countdownInterval);
            return;
        }
        var hours = Math.floor(diff / (1000 * 60 * 60));
        var minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
        var seconds = Math.floor((diff % (1000 * 60)) / 1000);
        $("#scan_countdown").text(
            "⏱ Next scan in: " +
            (hours > 0 ? hours + "h " : "") +
            minutes + "m " +
            seconds + "s"
        );
    }, 1000);
}

// Scan status updates
function renderScanStatus(msg) {
    $('#btn-stop-scan').prop('hidden', !msg.running).prop('disabled', !!msg.stopping);
    $("#scan_last").text(msg.last_scan    || "Never");
    $("#scan_next").text(msg.next_scan    || "—");
    $("#scan_progress").text(msg.stopping ? "Stopping scan..." : msg.current_step || "");

    if (msg.next_scan && msg.next_scan !== "Calculating..." && msg.next_scan !== "—") {
        updateCountdown(msg.next_scan);
    }
    setScanRunning(!!msg.running);
    if (msg.running) {
        $("#scan_box").addClass("scan-running");
        $("#scannowbtn").prop("disabled", true).text("Scanning...");
        $("#btn-scan-circular").prop("disabled", true).text("Scanning...");
        $("#scan_countdown").text("");
    } else {
        $("#scan_box").removeClass("scan-running");
        $("#scannowbtn").prop("disabled", false).text("6-Chamber Single Shot");
        $("#btn-scan-circular").prop("disabled", false).text("▶ Circular Scan Well");
    }
}

socket.on('scan_status', renderScanStatus);

$("#btn-stop-scan").click(function() {
    $.post("/scan/stop").done(function() {
        $.getJSON("/scan_status", renderScanStatus);
    }).fail(function() {
        $("#scan_progress").text("Stop unconfirmed. Please retry.");
    });
});

// Circular boustrophedon scan trigger & post-scan landmark verification
socket.on('scan_verify_prompt', function(info) {
    $("#scan-verify-text").text(
        "Scan of '" + info.well + "' complete (" + info.tiles_captured + "/" + info.tiles_total +
        " tiles). Returned to (0, 0) landmark — is the landmark centered?"
    );
    $("#scan-verify-banner").slideDown(150);
});

$("#btn-scan-circular").click(function() {
    var well = $("#scan-well-select").val() || "bottom_middle";
    var r    = parseInt($("#scan-geom-r").val(), 10)  || 1500;
    var sx   = parseInt($("#scan-geom-sx").val(), 10) || 500;
    var sy   = parseInt($("#scan-geom-sy").val(), 10) || 500;
    $("#scan-verify-banner").hide();
    $.ajax({
        url: "/nav/scan_well",
        method: "POST",
        contentType: "application/json",
        data: JSON.stringify({ well: well, radius: r, step_x: sx, step_y: sy }),
        error: function(xhr) {
            var msg = (xhr.responseJSON && xhr.responseJSON.error) ? xhr.responseJSON.error : "Could not start scan";
            alert(msg);
        }
    });
});

$("#btn-verify-yes").click(function() {
    $.post("/nav/verify_landmark", { centered: "true" });
    $("#scan-verify-banner").slideUp(150);
});

$("#btn-verify-no").click(function() {
    $.post("/nav/verify_landmark", { centered: "false" });
    $("#scan-verify-banner").slideUp(150);
});

// 6-Chamber Single Shot — position confirmation modal
$("#scannowbtn").click(function() {
    $("#position-modal-overlay").addClass("active");
});

$("#modal-yes").click(function() {
    $("#position-modal-overlay").removeClass("active");
    $.get("/scan_now");
});

$("#modal-no").click(function() {
    $("#position-modal-overlay").removeClass("active");
});

$("#position-modal-overlay").click(function(e) {
    if (e.target === this) {
        $(this).removeClass("active");
    }
});

// Organoid detection
$(".detectorganoid").click(function() {
    $.getJSON({ type: "GET", url: '/detect_organoid' });
});

socket.on('response3', function(msg) {
    document.getElementById('detection_image').src =
        "data:image/jpeg;base64," + msg.data;
});

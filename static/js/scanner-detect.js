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

    if (msg.next_scan_iso) {
        updateCountdown(msg.next_scan_iso);
    } else {
        clearInterval(window.countdownInterval);
        $("#scan_countdown").text("");
    }
    setScanRunning(!!msg.running);
    var circular = msg.running && msg.mode === "circular";
    var sixChamber = msg.running && msg.mode === "six_chamber";
    var modeLabel = circular ? "Circular Scan Well" : sixChamber ? "6-Chamber Single Shot" : "";
    $("#scan-mode-status").text(modeLabel ? modeLabel + " · " : "");
    $("#scan_box").toggleClass("scan-running", !!msg.running);
    $("#btn-scan-circular").prop("disabled", !!msg.running).toggleClass("active-scan", !!circular);
    $("#scannowbtn").prop("disabled", !!msg.running).toggleClass("active-scan", !!sixChamber);
    if (msg.running) $("#scan_countdown").text("");
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

var scheduleForm = document.getElementById("scan-schedule-form");
var scheduleFeedback = $("#schedule-feedback");
$(".scan-schedule").on("toggle", function() {
    if (!this.open) return;
    var fields = scheduleForm.elements;
    $(scheduleForm).find("fieldset").prop("disabled", true);
    scheduleFeedback.text("Loading schedule...");
    $.getJSON("/scan_schedule").done(function(settings) {
        fields.enabled.checked = settings.enabled;
        fields.start.value = settings.start;
        fields.end.value = settings.end;
        fields.interval.value = settings.interval;
        $(scheduleForm).find("fieldset").prop("disabled", false);
        scheduleFeedback.text("");
    }).fail(function() {
        scheduleFeedback.text("Could not load schedule. Reopen to retry.");
    });
});
$(scheduleForm).on("submit", function(event) {
    event.preventDefault();
    var fields = scheduleForm.elements;
    var settings = {enabled: fields.enabled.checked, start: fields.start.value,
        end: fields.end.value, interval: fields.interval.valueAsNumber};
    var fieldset = $(this).find("fieldset").prop("disabled", true);
    $.ajax({url: "/scan_schedule", method: "POST", contentType: "application/json",
        data: JSON.stringify(settings)}).done(function() {
        scheduleFeedback.text(settings.enabled ? "Daily schedule saved." : "Automatic scans disabled.");
    }).fail(function(xhr) {
        scheduleFeedback.text((xhr.responseJSON || {}).error || "Could not save schedule.");
    }).always(function() { fieldset.prop("disabled", false); });
});

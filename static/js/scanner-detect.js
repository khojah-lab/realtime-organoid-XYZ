// =========================
// SCANNER CONTROLS, LANDMARK VERIFY & ORGANOID DETECTION
// =========================

var nextScanIso = null;
var countdownTimer = null;

function showNextScan(iso, label) {
    var due = Date.parse(iso);
    if (!Number.isFinite(due)) iso = null;
    if (iso === nextScanIso) return;
    nextScanIso = iso;
    clearInterval(countdownTimer);
    $("#schedule-next").prop("hidden", !iso);
    if (!iso) return;

    $("#schedule-next-time").attr("datetime", iso).text(label);
    function tick() {
        var left = Math.ceil((due - Date.now()) / 1000);
        if (left <= 0) {
            $("#schedule-remaining").text("(due now)");
            clearInterval(countdownTimer);
            return;
        }
        var h = Math.floor(left / 3600);
        var m = Math.floor(left / 60) % 60;
        $("#schedule-remaining").text("(in " + (h ? h + "h " : "") + m + "m " + left % 60 + "s)");
    }
    countdownTimer = setInterval(tick, 1000);
    tick();
}

// Scan status updates
function renderScanStatus(msg) {
    $('#btn-stop-scan').prop('hidden', !msg.running).prop('disabled', !!msg.stopping);
    $("#scan_last").text(msg.last_scan || "No scan recorded");
    showNextScan(msg.next_scan_iso, msg.next_scan);
    $("#scan_progress").text(msg.stopping ? "Stopping scan..." : msg.current_step || "");

    setScanRunning(!!msg.running);
    var circular = msg.running && msg.mode === "circular";
    var sixChamber = msg.running && msg.mode === "six_chamber";
    var modeLabel = circular ? "Circular Scan Well" : sixChamber ? "6-Chamber Single Shot" : "";
    $("#scan-mode-status").text(modeLabel ? modeLabel + " · " : "");
    $("#scan_box").toggleClass("scan-running", !!msg.running);
    $("#btn-scan-circular").prop("disabled", !!msg.running).toggleClass("active-scan", !!circular);
    $("#scannowbtn").prop("disabled", !!msg.running).toggleClass("active-scan", !!sixChamber);
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
var savedSchedule;
var scheduleFields = scheduleForm.elements;

function showModeNote() {
    $("#schedule-well-note").prop("hidden", scheduleFields.mode.value !== "circular");
}

function displayScheduleDate(iso) {
    return iso.split("-").reverse().join("/");
}

function renderSchedule(settings) {
    savedSchedule = settings;
    if (!settings.enabled) showNextScan(null);
    scheduleFields.mode.value = settings.mode || "six_chamber";
    var today = new Intl.DateTimeFormat("sv-SE", {
        timeZone: "America/Los_Angeles", year: "numeric", month: "2-digit", day: "2-digit"
    }).format(new Date());
    scheduleFields.start_date.value = settings.start_date || today;
    scheduleFields.end_date.value = settings.end_date || "";
    scheduleFields.end_date.min = scheduleFields.start_date.value;
    scheduleFields.start.value = settings.start;
    scheduleFields.end.value = settings.end;
    scheduleFields.interval.value = settings.interval;
    showModeNote();
    scheduleForm.hidden = settings.enabled;
    $("#schedule-active").prop("hidden", !settings.enabled);
    $(scheduleForm).find("fieldset").prop("disabled", false);
    if (settings.enabled) {
        var mode = settings.mode === "circular"
            ? "Circular Scan Well (" + settings.circular.well + ")"
            : "6-Chamber Single Shot";
        var overnight = settings.end < settings.start ? " the next day" : "";
        var dates = settings.start_date ? " From " + displayScheduleDate(settings.start_date) : "";
        if (settings.end_date) dates += " through " + displayScheduleDate(settings.end_date) + " inclusive";
        $("#schedule-summary").text(mode + " runs every " + settings.interval + " min, daily from " +
            settings.start + " to " + settings.end + overnight + " (Los Angeles time)." + (dates ? dates + "." : ""));
    }
    scheduleFeedback.text(settings.enabled ? "" : "Automatic scanning is off.");
}

function submitSchedule(settings) {
    var controls = $(scheduleForm).find("fieldset").add("#schedule-cancel");
    controls.prop("disabled", true);
    $.ajax({url: "/scan_schedule", method: "POST", contentType: "application/json",
        data: JSON.stringify(settings)}).done(renderSchedule).fail(function(xhr) {
        scheduleFeedback.text((xhr.responseJSON || {}).error || "Schedule update unconfirmed. Refresh to check.");
    }).always(function() { controls.prop("disabled", false); });
}

socket.on("scan_schedule", renderSchedule);
$(scheduleFields.start_date).on("input", function() {
    scheduleFields.end_date.min = this.value;
});
$(scheduleFields.mode).on("change", showModeNote);
$.getJSON("/scan_schedule", renderSchedule).fail(function() {
    scheduleFeedback.text("Could not load automatic scan settings. Refresh to retry.");
});
$(scheduleForm).on("submit", function(event) {
    event.preventDefault();
    var settings = {enabled: true, mode: scheduleFields.mode.value, start: scheduleFields.start.value,
        end: scheduleFields.end.value, interval: scheduleFields.interval.valueAsNumber};
    settings.start_date = scheduleFields.start_date.value;
    settings.end_date = scheduleFields.end_date.value;
    if (settings.mode === "circular") {
        settings.circular = {well: $("#scan-well-select").val(),
            radius: document.getElementById("scan-geom-r").valueAsNumber,
            step_x: document.getElementById("scan-geom-sx").valueAsNumber,
            step_y: document.getElementById("scan-geom-sy").valueAsNumber};
    }
    submitSchedule(settings);
});
$("#schedule-cancel").on("click", function() {
    submitSchedule(Object.assign({}, savedSchedule, {enabled: false}));
});

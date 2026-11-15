// =========================
// IMAGE BROWSER
// =========================
var captureBrowser = {
    dates: [],          // [{date, scans}] newest first
    date: null,
    scans: [],          // scans on the current date
    scanIndex: -1,
    shown: [],          // captures of the current scan
    viewIndex: -1,
    selected: {}        // capture name -> bytes; survives changing scan or date
};

function formatBytes(bytes) {
    if (bytes < 1024 * 1024) return Math.max(1, Math.round(bytes / 1024)) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

function cbSetMessage(text) { $("#cb-message").text(text); }

function cbLoadDates(thenShowLatest) {
    $.getJSON("/captures/dates", function(response) {
        captureBrowser.dates = response.dates;
        if (response.dates.length === 0) {
            cbSetMessage("No captures in the cloud yet.");
            return;
        }
        var newest = response.dates[0].date;
        var oldest = response.dates[response.dates.length - 1].date;
        $("#cb-date").attr({ min: oldest, max: newest });
        if (thenShowLatest) cbShowDate(newest);
    }).fail(function() { cbSetMessage("Could not load the list of captures."); });
}

function cbShowDate(date) {
    captureBrowser.date = date;
    $("#cb-date").val(date);
    $("#cb-date-info").text("");
    $("#cb-scan-times, #cb-grid").empty();
    $("#cb-viewer").hide();
    cbSetMessage("Loading...");
    $.getJSON("/captures/scans", { date: date }, function(response) {
        captureBrowser.scans = response.scans;
        $("#cb-date-info").text(response.scans.length + " scan" + (response.scans.length === 1 ? "" : "s"));
        if (response.scans.length === 0) {
            cbSetMessage("No scans on this date. Use the arrows to jump to a day that has scans.");
            captureBrowser.scanIndex = -1;
            captureBrowser.shown = [];
            return;
        }
        cbSetMessage("");
        response.scans.forEach(function(scan, index) {
            $("<button type='button' class='cb-time'>").text(scan.time).data("index", index)
                .appendTo("#cb-scan-times");
        });
        cbShowScan(response.scans.length - 1);   // latest scan of the day
    }).fail(function() { cbSetMessage("Could not load scans for this date."); });
}

function cbShowScan(index) {
    captureBrowser.scanIndex = index;
    captureBrowser.shown = captureBrowser.scans[index].captures;
    $(".cb-time").each(function() { $(this).toggleClass("active", $(this).data("index") === index); });
    $("#cb-grid").empty();
    captureBrowser.shown.forEach(function(capture, position) {
        var card = $("<div class='cb-card'>").data("position", position);
        $("<img loading='lazy' alt=''>").attr("src", "/captures/image/" + capture.name + "?thumb=1")
            .addClass("cb-thumb").appendTo(card);
        $("<input type='checkbox' class='cb-check'>").prop("checked", !!captureBrowser.selected[capture.name])
            .attr("title", "Select for download").appendTo(card);
        $("<div class='cb-label'>").text(capture.chamber.replace("_", " ") + " " + capture.time).appendTo(card);
        card.appendTo("#cb-grid");
    });
    cbShowImage(0);
}

function cbShowImage(position) {
    var shown = captureBrowser.shown;
    if (shown.length === 0) return;
    position = (position + shown.length) % shown.length;
    captureBrowser.viewIndex = position;
    var capture = shown[position];
    $("#past_image").attr("src", "/captures/image/" + capture.name);
    $("#cb-caption").text(capture.chamber.replace("_", " ") + " \u00b7 " + captureBrowser.date + " " +
                          capture.time + " (" + (position + 1) + "/" + shown.length + ")");
    $(".cb-card").each(function() { $(this).toggleClass("viewing", $(this).data("position") === position); });
    $("#cb-viewer").show();
}

function cbUpdateSelection() {
    var names = Object.keys(captureBrowser.selected);
    var total = names.reduce(function(sum, name) { return sum + captureBrowser.selected[name]; }, 0);
    $("#cb-download-selected").prop("disabled", names.length === 0)
        .text(names.length === 0 ? "Download selected"
              : "Download " + names.length + " selected (" + formatBytes(total) + ")");
}

// Fetch as a blob rather than navigating, so an error shows here and the page is not replaced
function cbDownloadZip(query, button) {
    var label = button.text();
    button.prop("disabled", true);
    $("#cb-download-status").removeClass("cb-error").text("Preparing zip...");
    fetch("/captures/zip?" + query).then(function(response) {
        if (!response.ok) {
            return response.json().then(function(body) { throw new Error(body.error || "Download failed"); });
        }
        var filename = (response.headers.get("Content-Disposition") || "").split("filename=")[1] || "captures.zip";
        return response.blob().then(function(blob) {
            var link = document.createElement("a");
            link.href = URL.createObjectURL(blob);
            link.download = filename.replace(/"/g, "");
            document.body.appendChild(link);
            link.click();
            link.remove();
            setTimeout(function() { URL.revokeObjectURL(link.href); }, 10000);
            $("#cb-download-status").text("Downloaded " + formatBytes(blob.size));
        });
    }).catch(function(error) {
        $("#cb-download-status").addClass("cb-error").text(error.message);
    }).then(function() {
        button.prop("disabled", false).text(label);
        cbUpdateSelection();
    });
}

$(document).on("click", ".cb-time", function() { cbShowScan($(this).data("index")); });
$(document).on("click", ".cb-thumb", function() { cbShowImage($(this).closest(".cb-card").data("position")); });
$(document).on("change", ".cb-check", function() {
    var capture = captureBrowser.shown[$(this).closest(".cb-card").data("position")];
    if (this.checked) captureBrowser.selected[capture.name] = capture.bytes;
    else delete captureBrowser.selected[capture.name];
    cbUpdateSelection();
});

$("#cb-select-all").click(function() {
    captureBrowser.shown.forEach(function(capture) { captureBrowser.selected[capture.name] = capture.bytes; });
    $(".cb-check").prop("checked", true);
    cbUpdateSelection();
});
$("#cb-select-none").click(function() {
    captureBrowser.selected = {};
    $(".cb-check").prop("checked", false);
    cbUpdateSelection();
});

$("#cb-download-selected").click(function() {
    cbDownloadZip($.param({ name: Object.keys(captureBrowser.selected) }, true), $(this));
});
$("#cb-download-range").click(function() {
    var from = $("#datetime_from").val(), to = $("#datetime_to").val();
    if (!from || !to || to < from) {
        $("#cb-download-status").addClass("cb-error").text("Choose a From and a To, with To after From.");
        return;
    }
    cbDownloadZip($.param({ from: from, to: to }), $(this));
});

$("#cb-date").change(function() { if ($(this).val()) cbShowDate($(this).val()); });
$("#cb-latest").click(function() { cbLoadDates(true); });
function cbStepDay(direction) {   // direction -1 = older, +1 = newer (dates are listed newest first)
    var dates = captureBrowser.dates.map(function(entry) { return entry.date; });
    var candidates = dates.filter(function(date) {
        return direction < 0 ? date < captureBrowser.date : date > captureBrowser.date;
    });
    if (candidates.length === 0) return;
    cbShowDate(direction < 0 ? candidates[0] : candidates[candidates.length - 1]);
}
$("#cb-prev-day").click(function() { cbStepDay(-1); });
$("#cb-next-day").click(function() { cbStepDay(1); });
$("#cb-prev-image").click(function() { cbShowImage(captureBrowser.viewIndex - 1); });
$("#cb-next-image").click(function() { cbShowImage(captureBrowser.viewIndex + 1); });

$(document).on("keydown", function(event) {
    if ($(event.target).is("input, textarea, select") || $("#cb-viewer").is(":hidden")) return;
    if (event.key === "ArrowLeft")  cbShowImage(captureBrowser.viewIndex - 1);
    if (event.key === "ArrowRight") cbShowImage(captureBrowser.viewIndex + 1);
});

cbLoadDates(true);

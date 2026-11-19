// =========================
// STAGE NAVIGATION, BOOKMARKS & MOTION CONTROLS
// =========================
var tapStepsInput = document.getElementById("nav-tap-steps");
var WELL_GRID_ORDER = [
    "top_left", "top_middle", "top_right",
    "bottom_left", "bottom_middle", "bottom_right"
];

function formatSigned(val) {
    var n = parseInt(val || 0, 10);
    return (n >= 0 ? "+" : "") + n;
}

function updateNavUI(state) {
    if (!state) return;
    if (state.current_position) {
        $("#nav-pos-x").text(formatSigned(state.current_position.x));
        $("#nav-pos-y").text(formatSigned(state.current_position.y));
        $("#nav-pos-z").text(formatSigned(state.current_position.z));
    }
    $("#nav-uncertain-badge").toggle(!!state.position_uncertain);

    if (state.soft_limits) {
        $("#nav-lim-x").text(state.soft_limits.min_x + ", " + state.soft_limits.max_x);
        $("#nav-lim-y").text(state.soft_limits.min_y + ", " + state.soft_limits.max_y);
    }
    if (state.geometry && !$("#scan-geom-r").is(":focus") && !$("#scan-geom-sx").is(":focus") && !$("#scan-geom-sy").is(":focus")) {
        $("#scan-geom-r").val(state.geometry.well_radius_steps);
        $("#scan-geom-sx").val(state.geometry.step_x);
        $("#scan-geom-sy").val(state.geometry.step_y);
    }
    if (state.bookmarks) {
        var grid = $("#nav-bookmark-grid");
        grid.empty();
        var keys = WELL_GRID_ORDER.slice();
        Object.keys(state.bookmarks).forEach(function(k) {
            if (keys.indexOf(k) === -1) keys.push(k);
        });
        keys.forEach(function(name) {
            if (!(name in state.bookmarks)) return;
            var coords = state.bookmarks[name];
            var isCurrent = state.current_position &&
                state.current_position.x === coords[0] &&
                state.current_position.y === coords[1];

            var card = $('<div class="bm-card">').toggleClass("is-current", !!isCurrent);
            $('<div class="bm-title">').text(name).appendTo(card);
            $('<div class="bm-coords">').text('(' + coords[0] + ', ' + coords[1] + ')').appendTo(card);

            var actions = $('<div class="bm-actions">').appendTo(card);
            $('<button type="button" class="bm-go-btn">')
                .attr("data-name", name)
                .attr("title", "Move stage to " + name)
                .text("Go")
                .appendTo(actions);
            $('<button type="button" class="bm-sync-btn">')
                .attr("data-name", name)
                .attr("title", "Override software coordinates to " + name + " without moving motors")
                .text("Sync")
                .appendTo(actions);
            $('<button type="button" class="bm-set-btn">')
                .attr("data-name", name)
                .attr("title", "Overwrite " + name + " with current (X,Y)")
                .text("Set")
                .appendTo(actions);

            grid.append(card);
        });
    }
}

socket.on('nav_state', function(state) {
    updateNavUI(state);
});

$("#btn-nav-zero").click(function() {
    $.post("/nav/zero", function(state) {
        updateNavUI(state);
        $("#scan-verify-banner").slideUp(150);
    });
});

$(document).on("click", ".bm-go-btn", function() {
    var name = $(this).data("name");
    $.ajax({
        url: "/nav/goto",
        method: "POST",
        contentType: "application/json",
        data: JSON.stringify({ name: name })
    });
});

$(document).on("click", ".bm-sync-btn", function() {
    var name = $(this).data("name");
    $.ajax({
        url: "/nav/reset_to",
        method: "POST",
        contentType: "application/json",
        data: JSON.stringify({ name: name }),
        success: function(state) { updateNavUI(state); }
    });
});

$(document).on("click", ".bm-set-btn", function() {
    var name = $(this).data("name");
    if (!confirm("Overwrite bookmark '" + name + "' with current stage position?")) return;
    $.ajax({
        url: "/nav/mark",
        method: "POST",
        contentType: "application/json",
        data: JSON.stringify({ name: name }),
        success: function(state) { updateNavUI(state); }
    });
});

$("#btn-nav-goto-xy").click(function() {
    var tx = parseInt($("#nav-goto-x").val(), 10) || 0;
    var ty = parseInt($("#nav-goto-y").val(), 10) || 0;
    $.ajax({
        url: "/nav/goto",
        method: "POST",
        contentType: "application/json",
        data: JSON.stringify({ x: tx, y: ty })
    });
});

// ── Stepper Hold-to-Move & Scan Lock ─────────────────────────
// Press moves once; holding repeats until release. The server drops a request
// while the axis is still moving, so the repeat interval only needs to be short.
var HOLD_REPEAT_MS = 100;

var scanRunning  = false;
var scanOverride = false;  // user confirmed manual moves for the current scan
var MOVE_BUTTONS = "#btn-forward, #btn-backward, #btn-left, #btn-right, #btn-up, #btn-down";

function updateMotionLock() {
    $(MOVE_BUTTONS).prop("disabled", scanRunning && !scanOverride);
    $("#scan-lock-notice").toggle(scanRunning);
    $("#scan-unlock-btn").toggle(!scanOverride);
    $("#scan-lock-text").text(scanOverride
        ? "Manual override active. The rest of this scan will be misaligned."
        : "Scan in progress: manual movement is locked.");
}

function setScanRunning(running) {
    scanRunning = running;
    if (!running) scanOverride = false;
    updateMotionLock();
}

$("#scan-unlock-btn").click(function() {
    var confirmed = confirm(
        "A scan is running. Moving the stage manually will shift the remaining " +
        "chamber positions, because the motors have no position feedback.\n\n" +
        "Unlock manual movement anyway?");
    if (confirmed) {
        scanOverride = true;
        updateMotionLock();
    }
});

var stepPresets = document.querySelectorAll(".nav-step-preset");

function updateStepPresets() {
    stepPresets.forEach(function(button) {
        button.setAttribute("aria-pressed", Number(button.dataset.steps) === tapStepsInput.valueAsNumber);
    });
}

stepPresets.forEach(function(button) {
    button.addEventListener("click", function() {
        tapStepsInput.value = button.dataset.steps;
        updateStepPresets();
    });
});
tapStepsInput.addEventListener("input", updateStepPresets);
updateStepPresets();

function moveParams(steps, isRepeat) {
    var params = { steps: steps };
    if (isRepeat) {
        params.repeat = 1;
    }
    if (scanOverride) params.override = 1;
    return params;
}

function bindHoldToMove(buttonId, url) {
    var repeatTimer = null;
    var pressSteps;
    var pressStartMs = 0;
    var burstsAccepted = 0;   // responses of "OK"; the server answers "BUSY" mid-burst
    var requestsInFlight = 0;
    var reportWhenSettled = false;

    function sendMove(isRepeat) {
        requestsInFlight++;
        $.get(url, moveParams(pressSteps, isRepeat))
            .done(function(response) { if (response === "OK") burstsAccepted++; })
            .always(function() {
                requestsInFlight--;
                if (reportWhenSettled && requestsInFlight === 0) reportHoldEnd();
            });
    }

    // A single tap is already in the log as the press, so only report real holds
    function reportHoldEnd() {
        reportWhenSettled = false;
        if (burstsAccepted <= 1) return;
        $.get("/move_hold_end", {
            direction: url.slice(1),
            seconds: ((Date.now() - pressStartMs) / 1000).toFixed(1),
            bursts: burstsAccepted
        });
    }

    function stopRepeating() {
        if (repeatTimer === null) return;
        clearInterval(repeatTimer);
        repeatTimer = null;
        // The count is only final once the last responses have come back
        if (requestsInFlight === 0) reportHoldEnd(); else reportWhenSettled = true;
    }

    $(buttonId).on("pointerdown", function(event) {
        if (event.button !== 0 || repeatTimer !== null) return;
        if (!tapStepsInput.reportValidity()) return;
        pressSteps = tapStepsInput.valueAsNumber;
        pressStartMs = Date.now();
        burstsAccepted = 0;
        sendMove(false);
        repeatTimer = setInterval(function() { sendMove(true); }, HOLD_REPEAT_MS);
    });
    // Listen on window so releasing the pointer off the button still stops it
    $(window).on("pointerup pointercancel blur", stopRepeating);
    // Keyboard activation (Enter/Space) has no pointer events; detail is 0 for it
    $(buttonId).on("click", function(event) {
        if (event.detail === 0 && tapStepsInput.reportValidity()) $.get(url, moveParams(tapStepsInput.valueAsNumber, false));
    });
}

bindHoldToMove("#btn-forward",  "/forward");
bindHoldToMove("#btn-backward", "/backward");
bindHoldToMove("#btn-left",     "/left");
bindHoldToMove("#btn-right",    "/right");
bindHoldToMove("#btn-up",       "/up");
bindHoldToMove("#btn-down",     "/down");
$("#btn-stop").click(function() { $.get("/stop"); });

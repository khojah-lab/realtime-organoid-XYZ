// =========================
// SYSTEM PARAMETERS, LED, ZOOM/FOCUS & DC MOTORS
// =========================

// System parameters sync on load
socket.on('system_parameters_to_html', function(msg) {
    var r = msg.data.data;
    $("#zoom_text").html(r.zoom);          $("#zoom_slider").val(r.zoom);
    $("#focus_text").html(r.focus);        $("#focus_slider").val(r.focus);
    $("#motor_text").html(r.motor_speed);  $("#motor_slider").val(r.motor_speed);
    $("#spin_dur_text").html(r.spin_duration); $("#spin_dur_slider").val(r.spin_duration);
    $("#flowdir_text").html(r.flow_direction);
});

// ── LED Light Control ────────────────────────────────────────
$("#led-btn").click(function() {
    $.get("/led_toggle", function(state) {
        if (state === "1") {
            $("#led-btn").addClass("on");
        } else {
            $("#led-btn").removeClass("on");
        }
    });
});

socket.on('led_state', function(msg) {
    if (msg.state) {
        $("#led-btn").addClass("on");
    } else {
        $("#led-btn").removeClass("on");
    }
});

// ── Zoom / Focus & Autofocus ─────────────────────────────────
function fetchdata_zoom_focus() {
    $.getJSON({
        type: "GET",
        url: '/update_parameters_zoom_focus',
        data: { zoom: $('#zoom_slider').val(), focus: $('#focus_slider').val() }
    });
}

$("#zoom_slider").change(function()  { $("#zoom_text").html($(this).val());  fetchdata_zoom_focus(); });
$("#focus_slider").change(function() { $("#focus_text").html($(this).val()); fetchdata_zoom_focus(); });

$(".zoomplus").click(function() {
    var s = $("#zoom_slider"), v = Math.min(20000, +s.val() + +s.attr('step'));
    s.val(v); $("#zoom_text").html(v); fetchdata_zoom_focus();
});
$(".zoomminus").click(function() {
    var s = $("#zoom_slider"), v = Math.max(0, +s.val() - +s.attr('step'));
    s.val(v); $("#zoom_text").html(v); fetchdata_zoom_focus();
});
$(".focusplus").click(function() {
    var s = $("#focus_slider"), v = Math.min(20000, +s.val() + +s.attr('step'));
    s.val(v); $("#focus_text").html(v); fetchdata_zoom_focus();
});
$(".focusminus").click(function() {
    var s = $("#focus_slider"), v = Math.max(0, +s.val() - +s.attr('step'));
    s.val(v); $("#focus_text").html(v); fetchdata_zoom_focus();
});

$(".autofocusbutton").click(function() {
    $.getJSON({ type: "GET", url: '/autofocus_camera_from_html' });
});

// ── DC Motor 4-Channel Controls ──────────────────────────────
function dcSend(ch, speed, direction, duration) {
    $.get('/dc_motor', {
        ch: ch, speed: speed, direction: direction,
        duration: duration
    });
    updateDcStatus(ch, speed, direction);
}

var dcDirection = {};  // channel -> 'FORWARD' | 'BACKWARD' | 'STOP', as last known

function updateDcStatus(ch, speed, direction) {
    var el = $('#dc-st-' + ch);
    dcDirection[ch] = (speed == 0) ? 'STOP' : direction;
    el.removeClass('running reverse');
    if (direction === 'STOP' || speed == 0) {
        el.text('● Stopped');
    } else if (direction === 'FORWARD') {
        el.addClass('running').text('▶ Running FWD @ ' + parseFloat(speed).toFixed(2));
    } else {
        el.addClass('reverse').text('◀ Running REV @ ' + parseFloat(speed).toFixed(2));
    }
}

function syncDcSliderLabel(slider) {
    $('#dc-sv-' + $(slider).data('ch')).text(parseFloat($(slider).val()).toFixed(2));
}

$(document).on('input', '.dc-speed-slider', function() { syncDcSliderLabel(this); });

// Browsers can restore slider positions without firing 'input'
$(window).on('pageshow', function() {
    $('.dc-speed-slider').each(function() { syncDcSliderLabel(this); });
});

// Releasing a slider on a running channel applies the new speed immediately.
// Re-sends the duration field, which restarts that channel's auto-stop timer.
$(document).on('change', '.dc-speed-slider', function() {
    var ch = $(this).data('ch');
    var direction = dcDirection[ch];
    if (direction !== 'FORWARD' && direction !== 'BACKWARD') return;
    var dur = parseFloat($('#dc-duration').val()) || 0;
    dcSend(ch, parseFloat($(this).val()), direction, dur);
});

$(document).on('click', '.btn-fwd', function() {
    var ch  = $(this).data('ch');
    var spd = parseFloat($('.dc-speed-slider[data-ch=' + ch + ']').val());
    var dur = parseFloat($('#dc-duration').val()) || 0;
    dcSend(ch, spd, 'FORWARD', dur);
});

$(document).on('click', '.btn-rev', function() {
    var ch  = $(this).data('ch');
    var spd = parseFloat($('.dc-speed-slider[data-ch=' + ch + ']').val());
    var dur = parseFloat($('#dc-duration').val()) || 0;
    dcSend(ch, spd, 'BACKWARD', dur);
});

$(document).on('click', '.btn-stop-ch', function() {
    var ch = $(this).data('ch');
    $.get('/dc_motor_stop', { ch: ch });
    updateDcStatus(ch, 0, 'STOP');
});

$('#dc-all-stop').click(function() {
    $.get('/dc_motor_stop');
    for (var i = 1; i <= 4; i++) updateDcStatus(i, 0, 'STOP');
});

$('#dc-all-fwd').click(function() {
    var dur = parseFloat($('#dc-duration').val()) || 0;
    for (var i = 1; i <= 4; i++) {
        var spd = parseFloat($('.dc-speed-slider[data-ch=' + i + ']').val());
        dcSend(i, spd, 'FORWARD', dur);
    }
});

$('#dc-all-rev').click(function() {
    var dur = parseFloat($('#dc-duration').val()) || 0;
    for (var i = 1; i <= 4; i++) {
        var spd = parseFloat($('.dc-speed-slider[data-ch=' + i + ']').val());
        dcSend(i, spd, 'BACKWARD', dur);
    }
});

// Poll live state every 2 s (syncs status text if server auto-stopped after duration).
// Sliders are the pending speed for the next Fwd/Rev press, so they are not synced.
setInterval(function() {
    $.getJSON('/dc_motor_states', function(states) {
        $.each(states, function(ch, throttle) {
            ch = parseInt(ch, 10);
            var speed = Math.abs(throttle);
            var dir   = throttle > 0 ? 'FORWARD' : throttle < 0 ? 'BACKWARD' : 'STOP';
            updateDcStatus(ch, speed, dir);
        });
    });
}, 2000);

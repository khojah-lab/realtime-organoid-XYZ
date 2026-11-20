(() => {
    const el = id => document.getElementById("growth-" + id);
    const wells = Array.from(el("well").options).slice(1).map(option => option.value);
    const colors = ["#1769a1", "#b04a0e", "#28814d", "#8e4d9c", "#a37a00", "#236e77"];
    const zone = "America/Los_Angeles";
    const tooltip = el("detail");
    let pending;
    el("start").value = new Intl.DateTimeFormat("sv-SE", {
        timeZone: zone, year:"numeric", month:"2-digit", day:"2-digit"
    }).format(new Date());

    function svgNode(parent, tag, attrs, label) {
        const n = document.createElementNS("http://www.w3.org/2000/svg", tag);
        for (const [key, value] of Object.entries(attrs)) n.setAttribute(key, value);
        if (label !== undefined) n.textContent = label;
        parent.append(n);
        return n;
    }

    function describe(row) {
        const size = row.mean_diameter_px == null ? "—" : row.mean_diameter_px.toFixed(2) + " px";
        return [row.well.replace("_"," "), row.timestamp, "Count: " + row.count,
            "Mean diameter: " + size, "Scan ID: " + row.scan_id].join("\n");
    }

    function chart(id, metric, data, visible) {
        const host = el(id);
        host.replaceChildren();
        const width = Math.max(340, Math.min(1100, host.clientWidth)), height = 200;
        const left = 54, right = width - 44, top = 16, bottom = height - 36;
        const svg = svgNode(host, "svg", {viewBox: "0 0 " + width + " " + height,
            role:"group", "aria-label": metric === "count" ? "Count by capture time" : "Mean diameter by capture time"});
        // Use all captures for both charts, including fields without a diameter.
        const times = data.observations.map(row => Date.parse(row.timestamp));
        const start = times.reduce((a, b) => Math.min(a, b));
        const end = times.reduce((a, b) => Math.max(a, b));
        const span = end - start;
        const rows = data.observations.filter(row => row[metric] != null);
        const max = Math.max(1, Math.ceil(rows.reduce((m,row) => Math.max(m,row[metric]),0)));
        const x = row => span ? left + (Date.parse(row.timestamp)-start)/span*(right-left) : (left+right)/2;
        const y = row => bottom - row[metric]/max*(bottom-top);
        const ticks = metric === "count" ? Math.min(max,4) : 4;
        for (let i=0; i<=ticks; i++) {
            const value = metric === "count" ? Math.round(max*i/ticks) : max*i/ticks;
            const pos = bottom-value/max*(bottom-top);
            svgNode(svg,"line",{x1:left,x2:right,y1:pos,y2:pos,stroke:"#e2e8ef"});
            svgNode(svg,"text",{x:left-7,y:pos+4,"text-anchor":"end","font-size":11},Number(value.toFixed(1)));
        }
        const dateFmt = new Intl.DateTimeFormat("en-US", {timeZone:zone, month:"short", day:"numeric"});
        const showDate = dateFmt.format(start) !== dateFmt.format(end) || span >= 86400000;
        const clockFmt = new Intl.DateTimeFormat("en-US", {
            timeZone:zone, hour:"2-digit", minute:"2-digit", hourCycle:"h23",
            ...(span < 300000 ? {second:"2-digit"} : {})
        });
        const divisions = width < 480 ? 2 : 4;
        for (let i = 0; i <= (span ? divisions : 0); i++) {
            const fraction = span ? i/divisions : 0.5;
            const instant = start + span*fraction;
            const attrs = {x:left+(right-left)*fraction, y:bottom+16, "text-anchor":"middle", "font-size":11};
            svgNode(svg, "text", attrs, clockFmt.format(instant));
            if (showDate) svgNode(svg, "text", {...attrs, y:bottom+30}, dateFmt.format(instant));
        }
        for(const well of visible) {
            const points = rows.filter(row => row.well===well).sort((a,b)=>Date.parse(a.timestamp)-Date.parse(b.timestamp));
            const color = colors[wells.indexOf(well)];
            svgNode(svg,"polyline",{points:points.map(row=>x(row)+","+y(row)).join(" "),fill:"none",stroke:color,"stroke-width":2});
            for(const row of points) {
                const label = describe(row);
                const dot = svgNode(svg,"circle",{cx:x(row),cy:y(row),r:4,fill:color,tabindex:0,"aria-label":label});
                const show = () => {
                    tooltip.textContent=label; tooltip.hidden=false;
                    const box=dot.getBoundingClientRect();
                    tooltip.style.left=Math.max(4,Math.min(box.right+6,innerWidth-tooltip.offsetWidth-5))+"px";
                    tooltip.style.top=Math.max(4,Math.min(box.bottom+4,innerHeight-tooltip.offsetHeight-5))+"px";
                };
                for (const event of ["pointerenter","focus","click"]) dot.addEventListener(event,show);
                for (const event of ["pointerleave","blur"]) dot.addEventListener(event,()=>tooltip.hidden=true);
            }
        }
        if (!rows.length) svgNode(svg,"text",{x:width/2,y:height/2,"text-anchor":"middle"},"No diameter measurements");
    }

    async function load() {
        if (pending) pending.abort();
        const request = new AbortController();
        pending=request;
        tooltip.hidden=true; el("plots").hidden=true;
        if (!el("start").value) {el("status").textContent="Select a starting date.";return;}
        const well=el("well").value;
        const query=new URLSearchParams({start:el("start").value,days:el("range").value,well});
        el("status").textContent="Loading measurements…";
        try {
            const response=await fetch(el("analytics").dataset.url+"?"+query,{signal:request.signal});
            if (!response.ok) throw new Error("Could not load analytics. Try refreshing.");
            const data=await response.json();
            if (request.signal.aborted) return;
            if (!data.observations.length) {el("status").textContent="No measurements for this well and date range.";return;}
            el("status").textContent=data.observations.length+" field measurements · Capture time (Los Angeles)";
            const visible=well==="all"?wells:[well];
            el("legend").replaceChildren();
            for(const name of visible) {
                const item=document.createElement("span"), swatch=document.createElement("i");
                swatch.style.background=colors[wells.indexOf(name)];
                item.append(swatch,name.replace("_"," "));el("legend").append(item);
            }
            el("plots").hidden=false;
            chart("count","count",data,visible);chart("size","mean_diameter_px",data,visible);
        } catch(error) {if (!request.signal.aborted) el("status").textContent=error.message;}
    }
    for(const id of ["start","range","well"]) el(id).addEventListener("change",load);
    el("refresh").addEventListener("click",load);
    load();
})();

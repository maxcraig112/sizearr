/* app.js — fetches /api/media on a timer and renders the results table.
   TV shows expand to a per-episode size breakdown; movies are single rows. */
(function () {
  "use strict";

  var POLL_INTERVAL_MS = 5000;
  var table;
  var maxSize = 1;            // largest title size in the data set, for the bar scale
  var lastItemsJson = null;   // skip re-rendering the grid when data is unchanged
  var expanded = {};          // rowKey -> true, so open shows survive a redraw

  function formatBytes(bytes) {
    if (!bytes) return "0 B";
    var units = ["B", "KB", "MB", "GB", "TB"];
    var i = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
    var val = bytes / Math.pow(1024, i);
    return val.toFixed(val >= 100 || i === 0 ? 0 : 1) + " " + units[i];
  }

  function escapeHtml(str) {
    return String(str).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  function rowKey(d) {
    return d.category + "/" + d.name;
  }

  function hasChildren(d) {
    return !!(d && d.children && d.children.length);
  }

  function fatal(msg) {
    $("#subtitle").addClass("is-error").text(msg);
    $("#status").addClass("is-error").text(msg);
  }

  function renderExpander(data, type, row) {
    if (type !== "display") return "";
    return hasChildren(row) ? '<span class="expander"></span>' : "";
  }

  function renderCategory(data, type) {
    if (type !== "display") return data;
    var label = data === "movies" ? "Movies" : "TV";
    return '<span class="category-pill category-pill--' + data + '">' + label + "</span>";
  }

  function renderSize(data, type) {
    if (type !== "display") return data;
    var pct = Math.max(2, Math.round((data / maxSize) * 100));
    return (
      '<span class="size-cell">' +
      '<span class="size-cell__track"><span class="size-cell__fill" style="width:' + pct + '%"></span></span>' +
      '<span class="size-cell__bytes">' + formatBytes(data) + "</span>" +
      "</span>"
    );
  }

  function renderEpisodes(children) {
    var rows = children.map(function (c) {
      return (
        "<tr>" +
        '<td class="episode__name">' + escapeHtml(c.name) + "</td>" +
        '<td class="episode__size">' + formatBytes(c.size_bytes) + "</td>" +
        "</tr>"
      );
    }).join("");
    return '<div class="episodes"><table class="episodes__table"><tbody>' + rows + "</tbody></table></div>";
  }

  function toggleRow(tr) {
    var row = table.row(tr);
    var d = row.data();
    if (!hasChildren(d)) return;
    if (row.child.isShown()) {
      row.child.hide();
      tr.removeClass("is-expanded");
      delete expanded[rowKey(d)];
    } else {
      row.child(renderEpisodes(d.children)).show();
      tr.addClass("is-expanded");
      expanded[rowKey(d)] = true;
    }
  }

  function restoreExpanded() {
    table.rows().every(function () {
      var d = this.data();
      if (hasChildren(d) && expanded[rowKey(d)]) {
        this.child(renderEpisodes(d.children)).show();
        $(this.node()).addClass("is-expanded");
      }
    });
  }

  function initTable() {
    if (typeof $ === "undefined" || !$.fn || typeof $.fn.DataTable !== "function") {
      fatal("Failed to load page assets (jQuery / DataTables). Check the browser console and that /static/vendor/ is being served.");
      return false;
    }

    table = $("#mediaTable").DataTable({
      data: [],
      dom: 't<"dt-bottom"ilp>',
      columns: [
        { data: null, className: "col-expand", orderable: false, searchable: false, defaultContent: "", render: renderExpander },
        { data: "name", title: "Title", render: $.fn.dataTable.render.text() },
        { data: "category", title: "Category", render: renderCategory },
        { data: "size_bytes", title: "Size", className: "col-size", render: renderSize }
      ],
      order: [[3, "desc"]],
      pageLength: 25,
      lengthMenu: [[10, 25, 50, 100, 250], [10, 25, 50, 100, 250]],
      createdRow: function (rowEl, data) {
        if (hasChildren(data)) $(rowEl).addClass("has-children");
      },
      language: {
        info: "Showing _START_–_END_ of _TOTAL_",
        infoEmpty: "No titles",
        infoFiltered: " (from _MAX_)",
        lengthMenu: "Rows: _MENU_",
        zeroRecords: "No titles match your filter",
        paginate: { previous: "‹", next: "›" }
      }
    });

    $("#mediaTable tbody").on("click", "tr.has-children", function () {
      toggleRow($(this));
    });

    $("#categoryFilter").on("click", ".segmented__option", function () {
      $("#categoryFilter .segmented__option").removeClass("is-active");
      $(this).addClass("is-active");
      var cat = $(this).data("cat");
      table.column(2).search(cat ? "^" + cat + "$" : "", true, false).draw();
    });

    $("#search").on("input", function () {
      table.search(this.value).draw();
    });

    return true;
  }

  function setScanning(active, text) {
    $("#scanningPill").toggleClass("is-active", !!active);
    if (text) $("#scanningText").text(text);
  }

  function sumBytes(items) {
    return items.reduce(function (total, item) { return total + item.size_bytes; }, 0);
  }

  function renderGrid(items) {
    var itemsJson = JSON.stringify(items);
    if (itemsJson === lastItemsJson) return;
    lastItemsJson = itemsJson;

    maxSize = items.reduce(function (m, i) { return Math.max(m, i.size_bytes); }, 1);
    table.clear();
    table.rows.add(items);
    table.draw(false);
    restoreExpanded();
  }

  function renderStats(items, resp) {
    var movies = items.filter(function (i) { return i.category === "movies"; });
    var tv = items.filter(function (i) { return i.category === "tv"; });
    var lastScan = resp.last_scan ? new Date(resp.last_scan * 1000) : null;

    $("#statTitles").text(items.length);
    $("#statTotal").text(formatBytes(sumBytes(items)));
    $("#statMovies").html(formatBytes(sumBytes(movies)) + " <small>" + movies.length + " titles</small>");
    $("#statTv").html(formatBytes(sumBytes(tv)) + " <small>" + tv.length + " titles</small>");
    $("#statScan").html(
      lastScan
        ? lastScan.toLocaleDateString([], { month: "short", day: "numeric" }) +
          " <small>" + lastScan.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) + "</small>"
        : "—"
    );
  }

  function render(resp) {
    var items = resp.items || [];
    renderGrid(items);
    renderStats(items, resp);

    if (resp.scanning) {
      var since = resp.scan_started_at
        ? " · " + Math.round(Date.now() / 1000 - resp.scan_started_at) + "s"
        : "";
      setScanning(true, resp.progress || "Scanning…");
      $("#subtitle").removeClass("is-error").text((resp.progress || "Scanning your library…") + since);
      $("#status").removeClass("is-error").text("");
    } else if (resp.error) {
      setScanning(false);
      $("#subtitle").removeClass("is-error").text(items.length + " titles indexed");
      $("#status").addClass("is-error").text("Scan error: " + resp.error);
    } else {
      setScanning(false);
      $("#subtitle").removeClass("is-error").text("Largest titles first — click a TV show to see its episodes, or filter above.");
      $("#status").removeClass("is-error").text("");
    }
  }

  function loadData() {
    $.getJSON("/api/media")
      .done(render)
      .fail(function (xhr) {
        setScanning(false);
        $("#status").addClass("is-error")
          .text("Cannot reach /api/media (HTTP " + xhr.status + ") – is the server up?");
      });
  }

  function requestRescan() {
    var btn = $(this);
    btn.prop("disabled", true).text("Rescanning…");
    $("#status").removeClass("is-error").text("");
    $.post("/api/rescan").always(function () {
      setTimeout(function () {
        btn.prop("disabled", false).text("Rescan now");
      }, 1500);
      loadData();
    });
  }

  $(function () {
    if (!initTable()) return;
    loadData();
    setInterval(loadData, POLL_INTERVAL_MS);
    $("#rescanBtn").on("click", requestRescan);
  });
})();

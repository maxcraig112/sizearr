/* app.js — fetches /api/media on a timer and renders the results table.
   TV shows expand to a per-episode size breakdown; movies are single rows.
   When the server allows it, each row (and each episode) has a Delete button
   guarded by a confirmation modal. */
(function () {
  "use strict";

  var POLL_INTERVAL_MS = 5000;
  var table;
  var maxSize = 1;            // largest title size in the data set, for the bar scale
  var lastItemsJson = null;   // skip re-rendering the grid when data is unchanged
  var expanded = {};          // rowKey -> true, so open shows survive a redraw
  var canDelete = false;      // mirrors the server's ENABLE_DELETE
  var pendingDelete = null;   // {category, name, child, label} awaiting confirmation

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

  function renderActions(data, type, row) {
    if (type !== "display" || !canDelete) return "";
    var label = row.category === "tv" ? "Delete show" : "Delete";
    return '<button type="button" class="row-delete" data-action="delete">' + label + "</button>";
  }

  function renderEpisodes(item) {
    var nameAttr = ' data-name="' + escapeHtml(item.name) + '"';
    var rows = item.children.map(function (c) {
      var childAttr = ' data-child="' + escapeHtml(c.name) + '"';
      var del = canDelete
        ? '<button type="button" class="row-delete" data-action="delete-episode"' +
          nameAttr + childAttr + ">Delete</button>"
        : "";
      return (
        '<tr class="episode is-detailable"' + nameAttr + childAttr + ">" +
        '<td class="episode__name">' + escapeHtml(c.name) + "</td>" +
        '<td class="episode__size">' + formatBytes(c.size_bytes) + "</td>" +
        '<td class="episode__actions">' + del + "</td>" +
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
      row.child(renderEpisodes(d)).show();
      tr.addClass("is-expanded");
      expanded[rowKey(d)] = true;
    }
  }

  function restoreExpanded() {
    table.rows().every(function () {
      var d = this.data();
      if (hasChildren(d) && expanded[rowKey(d)]) {
        this.child(renderEpisodes(d)).show();
        $(this.node()).addClass("is-expanded");
      }
    });
  }

  /* ---- Delete confirmation modal ---- */

  function openConfirm(target) {
    pendingDelete = target;
    $("#confirmBody").text(
      'Permanently delete "' + target.label + '" from disk? This cannot be undone.'
    );
    $("#confirmError").prop("hidden", true).text("");
    $("#confirmDelete").prop("disabled", false).text("Delete");
    $("#confirmModal").prop("hidden", false);
    $("#confirmDelete").trigger("focus");
  }

  function closeConfirm() {
    pendingDelete = null;
    $("#confirmModal").prop("hidden", true);
  }

  function submitDelete() {
    if (!pendingDelete) return;
    var target = pendingDelete;
    var btn = $("#confirmDelete").prop("disabled", true).text("Deleting…");
    $.ajax({
      url: "/api/delete",
      method: "POST",
      contentType: "application/json",
      data: JSON.stringify({
        category: target.category,
        name: target.name,
        child: target.child
      })
    })
      .done(function () {
        closeConfirm();
        lastItemsJson = null; // force the grid to re-render on the next poll
        loadData();
      })
      .fail(function (xhr) {
        var msg = (xhr.responseJSON && xhr.responseJSON.error) || ("HTTP " + xhr.status);
        $("#confirmError").prop("hidden", false).text("Delete failed: " + msg);
        btn.prop("disabled", false).text("Delete");
      });
  }

  function onDeleteClick(e) {
    e.stopPropagation(); // don't also toggle the show's episode list
    var btn = $(this);
    if (btn.data("action") === "delete-episode") {
      openConfirm({
        category: "tv",
        name: String(btn.data("name")),
        child: String(btn.data("child")),
        label: String(btn.data("child"))
      });
      return;
    }
    var d = table.row(btn.closest("tr")).data();
    if (!d) return;
    openConfirm({
      category: d.category,
      name: d.name,
      child: null,
      label: d.name + (d.category === "tv" ? " (whole show)" : "")
    });
  }

  /* ---- Detail popup ---- */

  function fmtDateTime(iso) {
    if (!iso) return null;
    var d = new Date(iso);
    if (isNaN(d.getTime())) return escapeHtml(iso);
    return d.toLocaleString([], {
      year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"
    });
  }

  function fmtDuration(sec) {
    if (!sec) return null;
    var h = Math.floor(sec / 3600);
    var m = Math.floor((sec % 3600) / 60);
    var s = sec % 60;
    return (h ? h + "h " : "") + (h || m ? m + "m " : "") + s + "s";
  }

  function fmtBitrate(bps) {
    return bps ? (bps / 1e6).toFixed(1) + " Mbps" : null;
  }

  function chips(obj) {
    var order = ["resolution", "source", "video_codec", "dynamic_range", "audio",
                 "edition", "year", "episode", "release_group"];
    var used = {};
    var parts = [];
    order.forEach(function (k) {
      if (obj[k]) { used[k] = 1; parts.push('<span class="chip">' + escapeHtml(String(obj[k])) + "</span>"); }
    });
    Object.keys(obj).forEach(function (k) {
      if (!used[k] && obj[k]) parts.push('<span class="chip">' + escapeHtml(String(obj[k])) + "</span>");
    });
    return parts.length ? '<div class="chips">' + parts.join("") + "</div>" : "";
  }

  function defRow(label, valueHtml) {
    if (valueHtml == null || valueHtml === "") return "";
    return "<dt>" + escapeHtml(label) + "</dt><dd>" + valueHtml + "</dd>";
  }

  function renderMediaRows(m) {
    var out = "";
    out += defRow("Resolution", m.resolution ? escapeHtml(m.resolution) : null);
    out += defRow("Duration", fmtDuration(m.duration_seconds));
    out += defRow("Bitrate", fmtBitrate(m.bitrate));
    var video = [m.video_codec, m.hdr ? "HDR (" + m.hdr + ")" : null]
      .filter(Boolean).map(escapeHtml).join(" · ");
    out += defRow("Video", video || null);
    if (m.audio && m.audio.length) {
      out += defRow("Audio", m.audio.map(function (a) {
        return escapeHtml([a.codec, a.channels ? a.channels + "ch" : null, a.language, a.title]
          .filter(Boolean).join(" "));
      }).join("<br>"));
    }
    if (m.subtitles && m.subtitles.length) {
      out += defRow("Subtitles", m.subtitles.map(function (s) { return escapeHtml(String(s)); }).join(", "));
    }
    return out;
  }

  function renderDetail(d) {
    var rows = "";
    rows += defRow("Type", d.kind === "folder" ? "Folder" : "File");
    rows += defRow("Size", formatBytes(d.size_bytes));
    if (d.kind === "folder") {
      var exts = (d.extensions || []).map(function (e) { return e.count + "× " + e.ext; }).join(", ");
      rows += defRow("Files", d.file_count + (exts ? " — " + escapeHtml(exts) : ""));
    } else if (d.container) {
      rows += defRow("Container", escapeHtml(d.container));
    }
    rows += defRow("Modified", fmtDateTime(d.modified));
    rows += defRow(d.kind === "folder" ? "Oldest file" : "Created", fmtDateTime(d.oldest_file || d.created));

    if (d.name_tags && Object.keys(d.name_tags).length) {
      rows += defRow("From the name", chips(d.name_tags));
    }
    if (d.media) {
      rows += '<dt class="detail__section">Media (ffprobe)</dt><dd></dd>' + renderMediaRows(d.media);
    }
    if (d.primary_file) rows += defRow("Main video file", escapeHtml(d.primary_file));
    rows += defRow("Path", '<code class="detail__path">' + escapeHtml(d.path) + "</code>");
    return '<dl class="detail__list">' + rows + "</dl>";
  }

  function openDetail(category, name, child) {
    $("#detailTitle").text(child ? String(child).split("/").pop() : name);
    $("#detailBody").html('<p class="detail__loading">Loading…</p>');
    $("#detailModal").prop("hidden", false);
    $.getJSON("/api/detail", { category: category, name: name, child: child || "" })
      .done(function (d) { $("#detailBody").html(renderDetail(d)); })
      .fail(function (xhr) {
        var msg = (xhr.responseJSON && xhr.responseJSON.error) || ("HTTP " + xhr.status);
        $("#detailBody").html('<p class="modal__error">Could not load details: ' + escapeHtml(msg) + "</p>");
      });
  }

  function closeDetail() {
    $("#detailModal").prop("hidden", true);
  }

  function onRowDetailClick(e) {
    if ($(e.target).closest(".row-delete").length) return;
    var tr = $(this);
    if (tr.hasClass("episode")) {
      openDetail("tv", String(tr.data("name")), String(tr.data("child")));
      return;
    }
    var d = table.row(tr).data();
    if (d) openDetail(d.category, d.name, null);
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
        { data: "size_bytes", title: "Size", className: "col-size", render: renderSize },
        { data: null, className: "col-actions", orderable: false, searchable: false, defaultContent: "", render: renderActions }
      ],
      order: [[3, "desc"]],
      pageLength: 25,
      lengthMenu: [[10, 25, 50, 100, 250], [10, 25, 50, 100, 250]],
      createdRow: function (rowEl, data) {
        if (hasChildren(data)) $(rowEl).addClass("has-children");
        if (data.category === "movies") $(rowEl).addClass("is-detailable");
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

    var tbody = $("#mediaTable tbody");
    tbody.on("click", ".row-delete", onDeleteClick);
    tbody.on("click", "tr.is-detailable", onRowDetailClick);
    tbody.on("click", "tr.has-children", function () {
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

    $("#confirmModal").on("click", "[data-close]", closeConfirm);
    $("#confirmDelete").on("click", submitDelete);
    $("#detailModal").on("click", "[data-close-detail]", closeDetail);
    $(document).on("keydown", function (e) {
      if (e.key !== "Escape") return;
      if (!$("#detailModal").prop("hidden")) closeDetail();
      else if (!$("#confirmModal").prop("hidden")) closeConfirm();
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
    var wasDeletable = canDelete;
    canDelete = !!resp.can_delete;
    if (canDelete !== wasDeletable) lastItemsJson = null; // re-render to add/remove buttons

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

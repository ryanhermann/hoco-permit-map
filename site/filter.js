"use strict";
// Pure filter + URL-hash logic. Loaded as a plain script in the browser
// (window.Filters) and via require() in node tests. No ES modules — the
// site must work over file://.
(function (global) {
  const monthBoundary = (value, end) => {
    if (!/^\d{4}-\d{2}$/.test(value || "")) return value;
    if (!end) return value + "-01";
    const [year, month] = value.split("-").map(Number);
    const day = new Date(Date.UTC(year, month, 0)).getUTCDate();
    return `${value}-${String(day).padStart(2, "0")}`;
  };

  const Filters = {
    searchText(p) {
      return [p.id, p.type, p.contractor, p.description, p.address]
        .join(" ").toLowerCase();
    },

    matches(p, s) {
      if (s.q && !(p._search || Filters.searchText(p)).includes(s.q.toLowerCase())) {
        return false;
      }
      const issued = p.issued.slice(0, 10);
      if (s.from && issued < monthBoundary(s.from, false)) return false;
      if (s.to && issued > monthBoundary(s.to, true)) return false;
      if (s.cat !== "All" && p.category !== s.cat) return false;
      if (s.types.length && !s.types.includes(p.type)) return false;
      return true;
    },

    apply(permits, s) {
      return permits.filter((p) => Filters.matches(p, s));
    },

    normalizeRange(from, to) {
      return {
        from: monthBoundary(from || "", false),
        to: monthBoundary(to || "", true),
      };
    },

    lastMonths(latestDate, count, earliestDate) {
      if (!/^\d{4}-\d{2}-\d{2}$/.test(latestDate || "") ||
          !Number.isInteger(count) || count < 1) return { from: "", to: "" };
      const [year, month] = latestDate.split("-").map(Number);
      const firstMonth = year * 12 + month - 1 - (count - 1);
      const fromYear = Math.floor(firstMonth / 12);
      const fromMonth = firstMonth % 12 + 1;
      const calculatedFrom =
        `${fromYear}-${String(fromMonth).padStart(2, "0")}-01`;
      return {
        from: earliestDate && calculatedFrom < earliestDate
          ? earliestDate : calculatedFrom,
        to: latestDate,
      };
    },

    toHash(s) {
      const params = new URLSearchParams();
      if (s.q) params.set("q", s.q);
      if (s.from) params.set("from", s.from);
      if (s.to) params.set("to", s.to);
      if (s.cat !== "All") params.set("cat", s.cat);
      if (s.types.length) params.set("types", s.types.join("|"));
      const str = params.toString();
      return str ? "#" + str : "";
    },

    fromHash(hash) {
      const params = new URLSearchParams((hash || "").replace(/^#/, ""));
      const types = params.get("types");
      return {
        q: params.get("q") || "",
        from: params.get("from") || "",
        to: params.get("to") || "",
        cat: params.get("cat") || "All",
        types: types ? types.split("|") : [],
      };
    },
  };

  if (typeof module !== "undefined") module.exports = Filters;
  else global.Filters = Filters;
})(this);

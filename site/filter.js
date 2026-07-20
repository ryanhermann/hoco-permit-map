"use strict";
// Pure filter + URL-hash logic. Loaded as a plain script in the browser
// (window.Filters) and via require() in node tests. No ES modules — the
// site must work over file://.
(function (global) {
  const Filters = {
    searchText(p) {
      return [p.id, p.type, p.contractor, p.description, p.address]
        .join(" ").toLowerCase();
    },

    matches(p, s) {
      if (s.q && !(p._search || Filters.searchText(p)).includes(s.q.toLowerCase())) {
        return false;
      }
      const month = p.issued.slice(0, 7);
      if (s.from && month < s.from) return false;
      if (s.to && month > s.to) return false;
      if (s.cat !== "All" && p.category !== s.cat) return false;
      if (s.types.length && !s.types.includes(p.type)) return false;
      return true;
    },

    apply(permits, s) {
      return permits.filter((p) => Filters.matches(p, s));
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

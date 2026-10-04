/* pdfmini — a tiny dependency-free PDF writer (text + rules, Helvetica/Helvetica-Bold,
   multi-page). ~2KB. Enough for tabular reports. Non-ASCII is stripped (use "Rs"
   for currency; the base-14 fonts have no rupee glyph). Public API:
     var d = new PdfMini({margin:44});
     d.text(x, size, str, {bold, color:[r,g,b]});   // draws at the current y (baseline)
     d.line(x1, x2, {color, width});                // horizontal rule at current y
     d.moveDown(px);                                // advance down the page (auto page-break)
     d.addPage();
     d.save('report.pdf');                          // triggers a real download
*/
(function (global) {
  function PdfMini(o) {
    o = o || {};
    this.w = o.width || 595.28;   // A4 pt
    this.h = o.height || 841.89;
    this.margin = o.margin || 44;
    this.pages = [];
    this._c = "";
    this.y = this.h - this.margin;
  }
  var P = PdfMini.prototype;
  P._esc = function (s) {
    return String(s == null ? "" : s)
      .replace(/\\/g, "\\\\").replace(/\(/g, "\\(").replace(/\)/g, "\\)")
      .replace(/[^\x20-\x7e]/g, "");
  };
  P._rgb = function (c) { return (c[0] / 255).toFixed(3) + " " + (c[1] / 255).toFixed(3) + " " + (c[2] / 255).toFixed(3); };
  P._flush = function () { if (this._c) { this.pages.push(this._c); this._c = ""; } };
  P.addPage = function () { this._flush(); this.y = this.h - this.margin; };
  P.moveDown = function (d) { this.y -= d; if (this.y < this.margin) this.addPage(); };
  P.text = function (x, size, str, opt) {
    opt = opt || {};
    if (this.y < this.margin + size) this.addPage();
    var font = opt.bold ? "F2" : "F1";
    var c = "";
    if (opt.color) c += this._rgb(opt.color) + " rg\n";
    c += "BT /" + font + " " + size + " Tf " + (this.margin + x).toFixed(1) + " " + this.y.toFixed(1) + " Td (" + this._esc(str) + ") Tj ET\n";
    if (opt.color) c += "0 0 0 rg\n";
    this._c += c;
  };
  P.line = function (x1, x2, opt) {
    opt = opt || {};
    var col = opt.color || [200, 200, 200], w = opt.width || 0.7;
    this._c += this._rgb(col) + " RG " + w + " w " +
      (this.margin + x1).toFixed(1) + " " + this.y.toFixed(1) + " m " +
      (this.margin + x2).toFixed(1) + " " + this.y.toFixed(1) + " l S\n0 0 0 RG\n";
  };
  P.build = function () {
    this._flush();
    var objs = [];
    function add(s) { objs.push(s); return objs.length; }
    var catN = add(""), pagesN = add("");
    var f1N = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>");
    var f2N = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>");
    var kids = [];
    for (var i = 0; i < this.pages.length; i++) {
      var content = this.pages[i];
      var cN = add("<< /Length " + content.length + " >>\nstream\n" + content + "endstream");
      var pN = add("<< /Type /Page /Parent " + pagesN + " 0 R /MediaBox [0 0 " + this.w.toFixed(2) + " " + this.h.toFixed(2) +
        "] /Resources << /Font << /F1 " + f1N + " 0 R /F2 " + f2N + " 0 R >> >> /Contents " + cN + " 0 R >>");
      kids.push(pN + " 0 R");
    }
    objs[catN - 1] = "<< /Type /Catalog /Pages " + pagesN + " 0 R >>";
    objs[pagesN - 1] = "<< /Type /Pages /Kids [" + kids.join(" ") + "] /Count " + kids.length + " >>";
    var out = "%PDF-1.4\n", offsets = [];
    for (var j = 0; j < objs.length; j++) { offsets[j] = out.length; out += (j + 1) + " 0 obj\n" + objs[j] + "\nendobj\n"; }
    var xrefPos = out.length;
    out += "xref\n0 " + (objs.length + 1) + "\n0000000000 65535 f \n";
    for (var k = 0; k < objs.length; k++) out += ("0000000000" + offsets[k]).slice(-10) + " 00000 n \n";
    out += "trailer\n<< /Size " + (objs.length + 1) + " /Root " + catN + " 0 R >>\nstartxref\n" + xrefPos + "\n%%EOF";
    return out;
  };
  P.save = function (filename) {
    var pdf = this.build(), bytes = new Uint8Array(pdf.length);
    for (var i = 0; i < pdf.length; i++) bytes[i] = pdf.charCodeAt(i) & 0xff;
    var url = URL.createObjectURL(new Blob([bytes], { type: "application/pdf" }));
    var a = document.createElement("a");
    a.href = url; a.download = filename || "report.pdf";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  };
  global.PdfMini = PdfMini;
})(window);

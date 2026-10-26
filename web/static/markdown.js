/* Local, dependency-free Markdown renderer. It deliberately treats raw HTML as text. */
(function (global) {
  "use strict";
  var allowedUrl = /^(?:https?:|mailto:)/i;
  function uiLabel(key, fallback) { return global.YunhuI18n ? global.YunhuI18n.t(key) : fallback; }
  function safeUrl(value) {
    var url = String(value || "").trim();
    return allowedUrl.test(url) ? url : "";
  }
  function inline(parent, source) {
    var text = String(source == null ? "" : source);
    var i = 0, buffer = "";
    function flush() { if (buffer) { parent.append(document.createTextNode(buffer)); buffer = ""; } }
    while (i < text.length) {
      if (text[i] === "\\" && i + 1 < text.length && /[\\`*_{}\[\]()#+.!-]/.test(text[i + 1])) { buffer += text[i + 1]; i += 2; continue; }
      if (text[i] === "`" ) {
        var end = text.indexOf("`", i + 1);
        if (end > i + 1) { flush(); var code = document.createElement("code"); code.className = "inline-code"; code.textContent = text.slice(i + 1, end); parent.append(code); i = end + 1; continue; }
      }
      if (text[i] === "[" ) {
        var close = text.indexOf("](", i + 1), closeUrl = close < 0 ? -1 : text.indexOf(")", close + 2);
        if (close > i + 1 && closeUrl > close + 2) {
          var href = safeUrl(text.slice(close + 2, closeUrl));
          if (href) { flush(); var link = document.createElement("a"); link.href = href; link.target = "_blank"; link.rel = "noopener noreferrer"; inline(link, text.slice(i + 1, close)); parent.append(link); i = closeUrl + 1; continue; }
        }
      }
      var marker = text.slice(i);
      var matched = marker.match(/^(\*\*|__)(.+?)\1/);
      if (matched) { flush(); var strong = document.createElement("strong"); inline(strong, matched[2]); parent.append(strong); i += matched[0].length; continue; }
      matched = marker.match(/^(\*|_)([^\n]+?)\1/);
      if (matched) { flush(); var em = document.createElement("em"); inline(em, matched[2]); parent.append(em); i += matched[0].length; continue; }
      if (text[i] === "\n") { flush(); parent.append(document.createElement("br")); i++; continue; }
      buffer += text[i++];
    }
    flush();
  }
  function addTextBlock(parent, text) {
    var p = document.createElement("p"); inline(p, text); parent.append(p);
  }
  function render(root, source, options) {
    options = options || {};
    root.replaceChildren();
    var text = String(source == null ? "" : source).replace(/\r\n?/g, "\n");
    if (!text) return root;
    var lines = text.split("\n"), i = 0, paragraph = [];
    function flushParagraph() { if (paragraph.length) { addTextBlock(root, paragraph.join("\n")); paragraph = []; } }
    function codeBlock(codeText, language) {
      var wrap = document.createElement("div"); wrap.className = "code-block";
      var head = document.createElement("div"); head.className = "code-head";
      var label = document.createElement("span"); label.textContent = language || uiLabel("code_label", "代码");
      var copy = document.createElement("button"); copy.type = "button"; copy.className = "code-copy"; copy.textContent = uiLabel("copy", "复制"); copy.addEventListener("click", function () {
        var done = function () { copy.textContent = uiLabel("copy_done", "已复制"); setTimeout(function () { copy.textContent = uiLabel("copy", "复制"); }, 1300); };
        if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(codeText).then(done, function () { copy.textContent = uiLabel("copy_failed", "复制失败"); });
        else { var area = document.createElement("textarea"); area.value = codeText; area.style.position = "fixed"; area.style.opacity = "0"; document.body.append(area); area.select(); try { document.execCommand("copy"); done(); } catch (e) { copy.textContent = uiLabel("copy_failed", "复制失败"); } area.remove(); }
      });
      head.append(label, copy); var pre = document.createElement("pre"); var code = document.createElement("code"); code.textContent = codeText; pre.append(code); wrap.append(head, pre); root.append(wrap);
    }
    while (i < lines.length) {
      var line = lines[i];
      if (/^\s*```/.test(line)) {
        flushParagraph(); var language = line.replace(/^\s*```/, "").trim(), code = []; i++; while (i < lines.length && !/^\s*```/.test(lines[i])) code.push(lines[i++]); if (i < lines.length) i++; codeBlock(code.join("\n"), language); continue;
      }
      var heading = line.match(/^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$/);
      if (heading) { flushParagraph(); var h = document.createElement("h" + heading[1].length); inline(h, heading[2]); root.append(h); i++; continue; }
      if (/^\s*>/.test(line)) { flushParagraph(); var quote = document.createElement("blockquote"), quoteLines = []; while (i < lines.length && /^\s*>/.test(lines[i])) quoteLines.push(lines[i++].replace(/^\s*>\s?/, "")); render(quote, quoteLines.join("\n"), options); root.append(quote); continue; }
      if (/^\s*[-*+]\s+/.test(line) || /^\s*\d+[.)]\s+/.test(line)) {
        flushParagraph(); var ordered = /^\s*\d+[.)]\s+/.test(line), list = document.createElement(ordered ? "ol" : "ul");
        while (i < lines.length) { var item = lines[i].match(ordered ? /^\s*\d+[.)]\s+(.+)$/ : /^\s*[-*+]\s+(.+)$/); if (!item) break; var li = document.createElement("li"); inline(li, item[1]); list.append(li); i++; } root.append(list); continue;
      }
      if (!line.trim()) { flushParagraph(); i++; continue; }
      paragraph.push(line); i++;
    }
    flushParagraph(); return root;
  }
  global.SafeMarkdown = { render: render };
})(window);

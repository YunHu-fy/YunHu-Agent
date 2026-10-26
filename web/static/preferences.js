/* Display-only cache. Server settings remain authoritative; never contains credentials. */
(() => {
  "use strict";
  const defaults = Object.freeze({ui_theme:"system", ui_font_size:"md", ui_language:"zh"});
  const values = {ui_theme:["system","light","dark"], ui_font_size:["xs","sm","md","lg","xl"], ui_language:["zh","en"]};
  const validate = value => Object.fromEntries(Object.keys(defaults).map(key=>[key,values[key].includes(value?.[key])?value[key]:defaults[key]]));
  const media = window.matchMedia?.("(prefers-color-scheme: dark)");
  let current = {...defaults};
  try { current = validate(JSON.parse(localStorage.getItem("yunhu-display-v1") || "null")); } catch (_) {}
  function apply(value, persist=false) {
    current = validate(value);
    const dark = current.ui_theme === "dark" || (current.ui_theme === "system" && media?.matches);
    const root = document.documentElement;
    root.dataset.theme = dark?"dark":"light";
    root.dataset.themeMode = current.ui_theme;
    root.dataset.fontSize = current.ui_font_size;
    root.lang = current.ui_language === "en"?"en":"zh-CN";
    root.style.colorScheme = dark?"dark":"light";
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content",dark?"#15191f":"#f7f8fa");
    document.querySelector('meta[name="color-scheme"]')?.setAttribute("content",dark?"dark":"light");
    if(persist)try { localStorage.setItem("yunhu-display-v1",JSON.stringify(current)); } catch (_) {}
    window.dispatchEvent(new CustomEvent("yunhu:preferences",{detail:{...current}}));
    return {...current};
  }
  const systemChanged = () => { if(current.ui_theme === "system")apply(current); };
  if(media?.addEventListener)media.addEventListener("change",systemChanged);else media?.addListener?.(systemChanged);
  window.YunhuPreferences = Object.freeze({defaults,validate,apply,get:()=>({...current})});
  apply(current);
})();

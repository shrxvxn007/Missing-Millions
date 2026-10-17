const { chromium } = require("playwright-core");
(async () => {
  const browser = await chromium.launch({
    args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
  });
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await page.goto("http://127.0.0.1:8000/");
  await page.waitForTimeout(2500);
  const report = await page.evaluate(() => {
    const overflow = [];
    document.querySelectorAll("*").forEach((el) => {
      const box = el.getBoundingClientRect();
      if (box.right > window.innerWidth + 1 || box.left < -1) {
        overflow.push({
          tag: el.tagName,
          cls: String(el.className || "").slice(0, 44),
          left: Math.round(box.left),
          right: Math.round(box.right),
        });
      }
    });
    return { scrollW: document.documentElement.scrollWidth, inner: window.innerWidth, overflow: overflow.slice(0, 14) };
  });
  console.log(JSON.stringify(report, null, 1));
  await browser.close();
})();
